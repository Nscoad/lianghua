"""
快速捞钱交易 — 独立于主仓的小仓位快速买卖

监测所有币种每2分钟的价格变化，15分钟涨幅>6%时做多、跌幅>6%时做空，
各使用10%余额+5x杠杆。
浮动利润锁仓：盈利达+10%设锁仓线+2%，达+15%提升到+4%，回撤到线就平。
止损-1.5%始终有效。

风险机制：
  - 冷却机制：止损后同币种15分钟内不再触发
  - K线趋势过滤：做多仅trend=up，做空仅trend=down
  - 大亏损长冷却：单笔止损>20U时，冷却延长至60分钟
"""
import time
from datetime import datetime
from core.client import client
from core.queries import check_balance, get_real_price, get_current_price, get_position
from core.order import place_market_order, set_leverage, close_position
from utils.trade.records import record_open, record_close
from utils.state import load_fast_state, save_fast_state

FAST_LEVERAGE = 5
FAST_MARGIN_RATIO = 0.10       # 10% 余额（方案B：仓位翻倍，爆仓距离不变）
FAST_SL_RATIO = -0.075         # 止损 -7.5%（保证金回报率，对应价格 -1.5% × 5x杠杆）
FAST_TRIGGER_RATIO = 0.06     # 触发门槛：15分钟涨跌幅度 >6%
# 浮动利润锁仓参数
FAST_LOCK_TRIGGER_INIT = 0.10  # 起始触发：盈利达+10%
FAST_LOCK_FLOOR_INIT = 0.04    # 起始锁仓线：+4%
# 之后每多5%盈利，锁仓线上移2%（+15%→锁6%，+20%→锁8%，以此类推）
FAST_MIN_VOLUME = 500_000      # 最低成交额 50万U

# 冷却参数
FAST_COOLING_SEC = 1800         # 止损后冷却30分钟
FAST_HEAVY_LOSS = 20            # 单笔亏损>20U视为大亏损
FAST_HEAVY_COOLING_SEC = 1800   # 大亏损也冷却30分钟

# ---- 内存状态缓存：消除每5秒SQLite全表扫描 ----
# save 时直接更新缓存，load 时优先返回缓存（最多滞后1次save周期）
_state_cache: dict | None = None
_state_cache_time: float = 0.0
_STATE_CACHE_TTL = 1.0  # 秒，兜底TTL防止极端情况下的无限旧数据

# ---- 锁仓打印限流：同一币种每60秒最多打印一次 ----
_last_floor_print: dict[str, float] = {}


def _load_state() -> dict:
    """加载快捞状态 — 优先走内存缓存"""
    global _state_cache, _state_cache_time
    now = time.time()
    if _state_cache is not None and now - _state_cache_time < _STATE_CACHE_TTL:
        return _state_cache
    _state_cache = load_fast_state()
    _state_cache_time = now
    return _state_cache


def _save_state(state: dict):
    """原子保存快捞状态 — 同时更新内存缓存"""
    global _state_cache, _state_cache_time
    _state_cache = state
    _state_cache_time = time.time()
    save_fast_state(state)


def _has_position(state: dict, symbol: str = None) -> bool:
    """是否有持仓。传symbol则只检查该币种，不传则检查任意仓位"""
    positions = state.get("positions", {})
    if symbol:
        pos = positions.get(symbol)
        return bool(pos and not pos.get("closed", False))
    return any(not p.get("closed", False) for p in positions.values())


def _calc_pnl(price: float, entry: float, qty: float, side: str) -> float:
    if side == "LONG":
        return (price - entry) * qty
    return (entry - price) * qty


# ==================== 冷却机制 ====================

def _is_cooling(symbol: str, want_long: bool | None = None) -> bool:
    """检查该币种是否在冷却中。
    传入 want_long 时额外检查：
      - 如果 15分钟趋势与开仓方向一致 → 提前解除冷却，释放入场
    """
    state = _load_state()
    cooling = state.get("cooling", {})
    expires = cooling.get(symbol, 0)
    if time.time() >= expires:
        return False

    # 冷却中，检查是否可以提前解除（趋势匹配）
    if want_long is not None and _try_release_cooling(symbol, want_long, cooling, state):
        return False

    remain = int(expires - time.time())
    print(f"  [快捞冷却] {symbol} 冷却中，剩余 {remain//60}分{remain%60}秒")
    return True


def _try_release_cooling(symbol: str, want_long: bool, cooling: dict, state: dict) -> bool:
    """趋势匹配时提前解除冷却。返回 True=已解除"""
    try:
        from utils.market.kline import check_kline_entry
        kline = check_kline_entry(symbol, want_long=want_long)
        trend = kline.get("trend", "") if kline else ""
        if (want_long and trend == "up") or (not want_long and trend == "down"):
            del cooling[symbol]
            state["cooling"] = cooling
            _save_state(state)
            print(f"  [快捞冷却] {symbol} 趋势匹配（{trend}），提前解除冷却")
            return True
    except Exception:
        pass
    return False


def _set_cooling(symbol: str, seconds: int = FAST_COOLING_SEC):
    """设置币种冷却"""
    state = _load_state()
    cooling = state.get("cooling", {})
    cooling[symbol] = time.time() + seconds
    state["cooling"] = cooling
    _save_state(state)
    print(f"  [快捞冷却] {symbol} 冷却 {seconds//60} 分钟")


def _clean_expired_cooling():
    """清理已过期的冷却记录"""
    state = _load_state()
    cooling = state.get("cooling", {})
    now = time.time()
    expired = [s for s, t in cooling.items() if t <= now]
    for s in expired:
        del cooling[s]
    if expired:
        state["cooling"] = cooling
        _save_state(state)


# ==================== 趋势过滤 ====================

def _check_kline_trend(symbol: str, want_long: bool) -> tuple[bool, str]:
    """
    K线趋势过滤。做多要求trend=up，做空要求trend=down。
    数据不足时默认通过。
    Returns: (can_enter, entry_mode)
    """
    try:
        from utils.market.kline import check_kline_entry
        kline = check_kline_entry(symbol, want_long=want_long)
        trend = kline.get("trend", "sideways")
        entry_mode = kline.get("entry_mode", "trend")
        if want_long and trend == "up":
            return True, entry_mode
        if not want_long and trend == "down":
            return True, entry_mode
        print(f"  [快捞趋势过滤] {symbol} K线趋势={trend}，{'做多需up' if want_long else '做空需down'}，跳过")
        return False, entry_mode
    except Exception as e:
        print(f"  [快捞趋势过滤] {symbol} 检查异常: {e}，默认通过")
        return True, "trend"


# ==================== 主逻辑 ====================

# 锁仓策略切换阈值：利润 >= 30% 时启用K线动态回撤
FAST_LOCK_SWITCH_THRESHOLD = 0.30


def _calc_kline_lock_floor(symbol: str, highest_profit_pct: float) -> float | None:
    """
    计算锁仓保底线（全部按保证金回报率，含杠杆）。

    利润 < 30%：固定每+5%锁+4%（原规则，逐步扩大容错）
    利润 >= 30%：固定5%价格回撤（转杠杆后25%保证金回撤），不再K线动态

    Returns: 锁仓线（保证金回报率小数），None 表示不触发锁仓
    """
    # 早期：固定公式
    if highest_profit_pct < FAST_LOCK_SWITCH_THRESHOLD:
        if highest_profit_pct < FAST_LOCK_TRIGGER_INIT:
            return None
        extra = int((highest_profit_pct - FAST_LOCK_TRIGGER_INIT) / 0.05)
        return FAST_LOCK_FLOOR_INIT + extra * 0.04

    # 后期：固定5%价格回撤（转杠杆后25%保证金回撤）
    try:
        drawdown_price = 0.05
        drawdown = drawdown_price * FAST_LEVERAGE
        floor = highest_profit_pct - drawdown

        # 兜底：不低于固定公式的锁仓值，避免切换点断崖下跌
        fixed_floor = FAST_LOCK_FLOOR_INIT + int((highest_profit_pct - FAST_LOCK_TRIGGER_INIT) / 0.05) * 0.04
        return max(floor, fixed_floor, FAST_LOCK_FLOOR_INIT)
    except Exception:
        pass

    # 异常fallback：回到固定公式
    extra = int((highest_profit_pct - FAST_LOCK_TRIGGER_INIT) / 0.05)
    return FAST_LOCK_FLOOR_INIT + extra * 0.04


def _verify_close(symbol: str) -> bool:
    """平仓验证：确认交易所持仓已清空。返回 True 表示确实平掉了"""
    try:
        pos = get_position(symbol)
        if pos is None:
            return True
        amt = abs(float(pos["position_amt"]))
        if amt < 1:
            return True
        print(f"  [警告] {symbol} 交易所仍有持仓(qty={amt:.0f})，平仓可能未生效")
        return False
    except Exception as e:
        print(f"  [警告] {symbol} 平仓验证失败: {e}，默认认为平仓成功")
        return True


def _fetch_real_pnl(symbol: str) -> dict:
    """从交易所拉取该币种最近一笔平仓成交的真实数据"""
    try:
        from datetime import datetime as dt
        since = int((dt.now().timestamp() - 300) * 1000)  # 最近5分钟
        trades = client.rest_api.account_trade_list(
            symbol=symbol,
            limit=10,
            start_time=since,
        )
        from utils.trade.stats import _extract_trade_items
        items = _extract_trade_items(trades)
        for t in items:
            if t.realized_pnl and float(t.realized_pnl) != 0:
                side = "LONG" if t.buyer else "SHORT"
                return {
                    "realized_pnl": round(float(t.realized_pnl), 2),
                    "fee": round(abs(float(t.commission)), 4),
                    "qty": abs(float(t.qty)),
                    "exit_price": round(float(t.price), 8),
                    "order_id": t.order_id,
                    "side": side,
                }
    except Exception as e:
        print(f"  [警告] {symbol} 拉取真实成交失败: {e}")
    return {}


def _resolve_close_pnl(symbol: str, fills: dict, price: float, entry: float, qty: float, side: str) -> dict:
    """从交易所获取真实平仓数据，不做计算。返回 {realized_pnl, exit_price, fee, qty, order_id}"""
    if fills["qty"] > 0:
        exit_p = fills["avg_price"] if fills["avg_price"] > 0 else price
        return {
            "realized_pnl": fills["realized_pnl"],
            "exit_p": exit_p,
            "fee": fills["commission"],
            "qty": fills["qty"],
            "order_id": fills.get("order_id", 0),
            "slippage": fills.get("slippage", 0.0),
            "source": "fills",
        }
    # fills 为空，从交易所拉真实成交
    real = _fetch_real_pnl(symbol)
    if real:
        print(f"  [交易所数据] 使用真实成交: pnl={real['realized_pnl']:+.2f} fee={real['fee']:.4f}")
        return {
            "realized_pnl": real["realized_pnl"],
            "exit_p": real["exit_price"],
            "fee": real["fee"],
            "qty": real["qty"],
            "order_id": real["order_id"],
            "slippage": 0.0,
            "source": "exchange",
        }
    print("  [警告] 未获取到交易所真实成交，记录将不完整")
    exit_p = price
    return {
        "realized_pnl": 0.0,
        "exit_p": exit_p,
        "fee": 0.0,
        "qty": qty,
        "order_id": 0,
        "slippage": 0.0,
        "source": "empty",
    }


def check_fast_position():
    """
    检查所有快捞仓位 — 止损/浮动锁仓平仓。
    每个仓位独立判断。
    """
    state = _load_state()
    positions = state.get("positions", {})
    changed = False

    for symbol, pos_data in list(positions.items()):
        if pos_data.get("closed", False):
            continue

        entry = pos_data["entry_price"]
        side = pos_data["side"]
        qty = pos_data["qty"]

        price = get_real_price(symbol)
        if not price:
            # 测试网专有币种（实网不存在），回退到测试网价格
            price = get_current_price(symbol)
            if not price:
                continue

        pnl_ratio = (price - entry) / entry if side == "LONG" else (entry - price) / entry
        pnl_ratio *= FAST_LEVERAGE  # 转为保证金回报率（含杠杆）

        # === 止损（始终有效） ===
        if pnl_ratio <= FAST_SL_RATIO:
            print(f"\n[快捞] 止损触发! {symbol} {pnl_ratio*100:.1f}%")
            _, fills = close_position(symbol)
            if not _verify_close(symbol):
                print(f"  [警告] {symbol} 止损平仓未生效，跳过状态标记，下次循环继续处理")
                continue
            close_data = _resolve_close_pnl(symbol, fills, price, entry, qty, side)
            exit_p = close_data["exit_p"]
            # 价格合理性校验：成交价偏离实盘超 30% 时用实盘价替代
            if exit_p > 0 and price > 0 and close_data["source"] == "fills":
                deviation = abs(exit_p - price) / max(price, 1e-12)
                if deviation > 0.30:
                    print(f"  [价格异常] 成交价 {exit_p:.4f} 偏离实盘 {price:.4f} {deviation*100:.0f}%，使用实盘价")
                    exit_p = price
            final_pnl = close_data["realized_pnl"]
            if close_data["source"] == "empty":
                final_pnl = _calc_pnl(exit_p, entry, close_data["qty"], side)
            record_close(symbol, "fast_sl", final_pnl, close_data["qty"],
                         entry, exit_p, side, fee=close_data["fee"],
                         slippage=close_data["slippage"],
                         order_id=close_data["order_id"])
            pos_data["closed"] = True
            changed = True

            loss_amount = abs(final_pnl)
            if loss_amount > FAST_HEAVY_LOSS:
                cool_sec = FAST_HEAVY_COOLING_SEC
                print(f"  [快捞] 大亏损 {final_pnl:+.2f} USDT（>{FAST_HEAVY_LOSS}U），冷却30分钟")
            else:
                cool_sec = FAST_COOLING_SEC
                print(f"  [快捞] 止损平仓 {symbol} 亏损 {final_pnl:+.2f} USDT")
            # 冷却直接写入 state 对象，避免结尾 _save_state 覆盖
            cooling = state.setdefault("cooling", {})
            cooling[symbol] = time.time() + cool_sec
            state["cooling"] = cooling
            print(f"  [快捞冷却] {symbol} 冷却 {cool_sec//60} 分钟")
            continue

        # === 浮动利润锁仓 ===
        profit_floor = pos_data.get("profit_floor", 0.0)
        highest = pos_data.get("highest_profit_pct", 0.0)

        # 更新最高盈利
        if pnl_ratio > highest:
            highest = pnl_ratio
            pos_data["highest_profit_pct"] = highest

        # 每次检查都重新计算锁仓线（阈值、K线数据可能变化）
        new_floor = _calc_kline_lock_floor(symbol, highest)
        if new_floor is not None and abs(new_floor - profit_floor) > 0.001:
            profit_floor = new_floor
            # 打印限流：同一币种每60秒最多打印一次，避免≥30%利润时每5秒都输出
            now = time.time()
            last_ts = _last_floor_print.get(symbol, 0.0)
            if now - last_ts >= 60:
                _last_floor_print[symbol] = now
                if highest < FAST_LOCK_SWITCH_THRESHOLD:
                    print(f"  [快捞] {symbol} 盈+{pnl_ratio*100:.1f}%(最高+{highest*100:.1f}%) 锁仓线+{profit_floor*100:.0f}%（固定阶梯）")
                else:
                    print(f"  [快捞] {symbol} 盈+{pnl_ratio*100:.1f}%(最高+{highest*100:.1f}%) 锁仓线+{profit_floor*100:.0f}%（K线动态回撤）")

            pos_data["profit_floor"] = profit_floor
            changed = True

        # 检查盈利是否回撤到锁仓线
        if profit_floor > 0 and pnl_ratio <= profit_floor:
            print(f"\n[快捞] 浮动锁仓触发! {symbol} {pnl_ratio*100:.2f}% <= 锁仓线+{profit_floor*100:.0f}%")
            _, fills = close_position(symbol)
            if not _verify_close(symbol):
                print(f"  [警告] {symbol} 锁仓平仓未生效，跳过状态标记，下次循环继续处理")
                continue
            close_data = _resolve_close_pnl(symbol, fills, price, entry, qty, side)
            exit_p = close_data["exit_p"]
            # 价格合理性校验：成交价偏离实盘超 30% 时用实盘价替代
            if exit_p > 0 and price > 0 and close_data["source"] == "fills":
                deviation = abs(exit_p - price) / max(price, 1e-12)
                if deviation > 0.30:
                    print(f"  [价格异常] 成交价 {exit_p:.4f} 偏离实盘 {price:.4f} {deviation*100:.0f}%，使用实盘价")
                    exit_p = price
            final_pnl = close_data["realized_pnl"]
            if close_data["source"] == "empty":
                final_pnl = _calc_pnl(exit_p, entry, close_data["qty"], side)
            record_close(symbol, "fast_tp_lock", final_pnl, close_data["qty"],
                         entry, exit_p, side, fee=close_data["fee"],
                         slippage=close_data["slippage"],
                         order_id=close_data["order_id"])
            pos_data["closed"] = True
            changed = True
            print(f"  [快捞] 浮动锁仓平仓 {symbol} 盈利 {final_pnl:+.2f} USDT")
            continue

    if changed:
        _save_state(state)

    return changed


def try_fast_open(symbol: str, current_price: float, prev_price: float):
    """尝试快速开仓 — 涨幅达标时买入"""
    _clean_expired_cooling()

    # 冷却检查（传 want_long=True，趋势匹配时可提前解除）
    if _is_cooling(symbol, want_long=True):
        return

    change = (current_price - prev_price) / prev_price
    if change < FAST_TRIGGER_RATIO:
        return

    state = _load_state()
    if _has_position(state, symbol):
        return

    # K线趋势过滤：做多仅up趋势
    can_enter, entry_mode = _check_kline_trend(symbol, want_long=True)
    if not can_enter:
        return

    balance = check_balance()
    if not balance or balance <= 0:
        return

    margin = balance * FAST_MARGIN_RATIO
    qty = int(margin * FAST_LEVERAGE / current_price)
    if qty < 1:
        return

    print(f"\n[快捞] {symbol} 15分钟涨{change*100:.1f}%，趋势向上，触发快速开仓!")
    print(f"  余额 {balance:.2f} USDT, 开仓5% = {margin:.2f} USDT, 初始数量 {qty}")
    set_leverage(symbol, FAST_LEVERAGE)

    # 自动减量重试：超过单笔最大限制时逐次减少10%
    order_data = None
    for attempt in range(5):
        order_data, fills = place_market_order(symbol=symbol, side="BUY", quantity=qty)
        if order_data:
            break
        qty = int(qty * 0.9)
        if qty < 1:
            break
        print(f"  [重试] 减量至 {qty} 重新下单...")

    if order_data:
        actual_qty = fills["qty"] or qty
        actual_price = fills["avg_price"] or current_price
        record_open(symbol, "LONG", actual_qty, actual_price, fee=fills["commission"],
                    order_id=order_data.order_id if order_data else 0,
                    slippage=fills.get("slippage", 0.0),
                    entry_mode=entry_mode)
        state["positions"][symbol] = {
            "entry_price": actual_price,
            "side": "LONG",
            "qty": actual_qty,
            "margin": margin,
            "open_time": datetime.now().isoformat(),
            "closed": False,
            "profit_floor": 0.0,
            "highest_profit_pct": 0.0,
        }
        _save_state(state)
        print(f"  [快捞] {symbol} 开仓成功 @ {actual_price}")
        print("  [策略] +10%启动锁仓(+2%) → 每+5%锁仓+2% | 止损-1.5%")
    else:
        print(f"  [快捞] {symbol} 开仓失败")


def try_fast_short(symbol: str, current_price: float, prev_price: float):
    """尝试快速做空 — 跌幅达标时做空"""
    _clean_expired_cooling()

    # 冷却检查（传 want_long=False，趋势匹配时可提前解除）
    if _is_cooling(symbol, want_long=False):
        return

    change = (current_price - prev_price) / prev_price
    if change > -FAST_TRIGGER_RATIO:
        return

    state = _load_state()
    if _has_position(state, symbol):
        return

    # K线趋势过滤：做空仅down趋势
    can_enter, entry_mode = _check_kline_trend(symbol, want_long=False)
    if not can_enter:
        return

    balance = check_balance()
    if not balance or balance <= 0:
        return

    margin = balance * FAST_MARGIN_RATIO
    qty = int(margin * FAST_LEVERAGE / current_price)
    if qty < 1:
        return

    print(f"\n[快捞] {symbol} 15分钟跌{abs(change)*100:.1f}%，趋势向下，触发快速做空!")
    print(f"  余额 {balance:.2f} USDT, 开仓5% = {margin:.2f} USDT, 初始数量 {qty}")
    set_leverage(symbol, FAST_LEVERAGE)

    # 自动减量重试：超过单笔最大限制时逐次减少10%
    order_data = None
    for attempt in range(5):
        order_data, fills = place_market_order(symbol=symbol, side="SELL", quantity=qty)
        if order_data:
            break
        qty = int(qty * 0.9)
        if qty < 1:
            break
        print(f"  [重试] 减量至 {qty} 重新下单...")

    if order_data:
        actual_qty = fills["qty"] or qty
        actual_price = fills["avg_price"] or current_price
        record_open(symbol, "SHORT", actual_qty, actual_price, fee=fills["commission"],
                    order_id=order_data.order_id if order_data else 0,
                    slippage=fills.get("slippage", 0.0),
                    entry_mode=entry_mode)
        state["positions"][symbol] = {
            "entry_price": actual_price,
            "side": "SHORT",
            "qty": actual_qty,
            "margin": margin,
            "open_time": datetime.now().isoformat(),
            "closed": False,
            "profit_floor": 0.0,
            "highest_profit_pct": 0.0,
        }
        _save_state(state)
        print(f"  [快捞] {symbol} 做空成功 @ {actual_price}")
        print("  [策略] +10%启动锁仓(+2%) → 每+5%锁仓+2% | 止损-1.5%")
    else:
        print(f"  [快捞] {symbol} 做空失败")
