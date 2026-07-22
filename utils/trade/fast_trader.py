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
from core.queries import check_balance, get_current_price
from core.order import place_market_order, set_leverage, close_position
from utils.trade.records import record_open, record_close
from utils.state import load_fast_state, save_fast_state

FAST_LEVERAGE = 5
FAST_MARGIN_RATIO = 0.10       # 10% 余额（方案B：仓位翻倍，爆仓距离不变）
FAST_SL_RATIO = -0.075         # 止损 -7.5%（保证金回报率，对应价格 -1.5% × 5x杠杆）
FAST_TRIGGER_RATIO = 0.06     # 触发门槛：15分钟涨跌幅度 >6%
# 浮动利润锁仓参数
FAST_LOCK_TRIGGER_INIT = 0.10  # 起始触发：盈利达+10%
FAST_LOCK_FLOOR_INIT = 0.02    # 起始锁仓线：+2%
# 之后每多5%盈利，锁仓线上移2%（+15%→锁4%，+20%→锁6%，以此类推）
FAST_MIN_VOLUME = 500_000      # 最低成交额 50万U

# 冷却参数
FAST_COOLING_SEC = 900          # 止损后冷却15分钟
FAST_HEAVY_LOSS = 20            # 单笔亏损>20U视为大亏损
FAST_HEAVY_COOLING_SEC = 3600   # 大亏损冷却60分钟


def _load_state() -> dict:
    """加载快捞状态（含 JSON→SQLite 自动迁移）"""
    return load_fast_state()


def _save_state(state: dict):
    """原子保存快捞状态"""
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

def _is_cooling(symbol: str) -> bool:
    """检查该币种是否在冷却中"""
    state = _load_state()
    cooling = state.get("cooling", {})
    expires = cooling.get(symbol, 0)
    if time.time() < expires:
        remain = int(expires - time.time())
        print(f"  [快捞冷却] {symbol} 冷却中，剩余 {remain//60}分{remain%60}秒")
        return True
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

def _check_kline_trend(symbol: str, want_long: bool) -> bool:
    """
    K线趋势过滤。做多要求trend=up，做空要求trend=down。
    数据不足时默认通过。
    """
    try:
        from utils.market.kline import check_kline_entry
        kline = check_kline_entry(symbol, want_long=want_long)
        trend = kline.get("trend", "sideways")
        if want_long and trend == "up":
            return True
        if not want_long and trend == "down":
            return True
        print(f"  [快捞趋势过滤] {symbol} K线趋势={trend}，{'做多需up' if want_long else '做空需down'}，跳过")
        return False
    except Exception as e:
        print(f"  [快捞趋势过滤] {symbol} 检查异常: {e}，默认通过")
        return True


# ==================== 主逻辑 ====================

# 锁仓策略切换阈值：利润 >= 30% 时启用K线动态回撤
FAST_LOCK_SWITCH_THRESHOLD = 0.30


def _calc_kline_lock_floor(symbol: str, highest_profit_pct: float) -> float | None:
    """
    基于K线波动计算动态锁仓保底线（全部按保证金回报率，含杠杆）。

    利润 < 30%：固定每+5%锁+2%（原规则，逐步扩大容错）
    利润 >= 30%：K线动态回撤
      - 用最近1小时振幅判断当前波动速度（币圈波动快）
      - 振幅大 → 允许更大回撤，让利润奔跑
      - 强趋势 → 允许更大回撤，不轻易下车
      - 弱趋势/横盘 → 收紧回撤, 落袋为安

    Returns: 锁仓线（保证金回报率小数），None 表示不触发锁仓
    """
    # 早期：固定公式
    if highest_profit_pct < FAST_LOCK_SWITCH_THRESHOLD:
        if highest_profit_pct < FAST_LOCK_TRIGGER_INIT:
            return None
        extra = int((highest_profit_pct - FAST_LOCK_TRIGGER_INIT) / 0.05)
        return FAST_LOCK_FLOOR_INIT + extra * 0.02

    # 后期：K线动态回撤
    try:
        from utils.market.kline import get_kline_levels

        # 取最近6根1h K线算振幅（需>=6根，避免数据不足回退到固定公式）
        hourly_levels = get_kline_levels(symbol, lookback=6)
        if not hourly_levels or not hourly_levels.get("current_price"):
            raise ValueError("no kline data")

        price = hourly_levels["current_price"]
        h1 = hourly_levels.get("prev_high", price)
        l1 = hourly_levels.get("prev_low", price)
        hourly_range = (h1 - l1) / price if price > 0 else 0.02
        hourly_range = max(hourly_range, 0.01)  # 至少1%

        # 趋势强度系数：强趋势2x，横盘1x（用更多K线判断趋势）
        trend_levels = get_kline_levels(symbol, lookback=24)
        trend = trend_levels.get("trend", "sideways") if trend_levels else "sideways"
        trend_mult = 2.0 if trend in ("up", "down") else 1.0

        # 允许回撤 = 至少5%，基于6h振幅×趋势系数（×4倍外推，上限8%价格回撤），再乘杠杆转保证金回报率
        drawdown_price = max(0.05, min(hourly_range * trend_mult * 4, 0.08))
        drawdown = drawdown_price * FAST_LEVERAGE

        # 锁仓线 = 最高盈利 - 允许回撤
        floor = highest_profit_pct - drawdown
        return max(floor, FAST_LOCK_FLOOR_INIT)  # 至少保住+2%
    except Exception:
        pass

    # 异常fallback：回到固定公式
    extra = int((highest_profit_pct - FAST_LOCK_TRIGGER_INIT) / 0.05)
    return FAST_LOCK_FLOOR_INIT + extra * 0.02


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

        price = get_current_price(symbol)
        if not price:
            continue

        pnl_ratio = (price - entry) / entry if side == "LONG" else (entry - price) / entry
        pnl_ratio *= FAST_LEVERAGE  # 转为保证金回报率（含杠杆）

        # === 止损（始终有效） ===
        if pnl_ratio <= FAST_SL_RATIO:
            print(f"\n[快捞] 止损触发! {symbol} {pnl_ratio*100:.1f}%")
            _, fills = close_position(symbol)
            exit_p = fills["avg_price"] if fills["avg_price"] > 0 else price
            final_pnl = fills["realized_pnl"] if fills["qty"] > 0 else _calc_pnl(price, entry, qty, side)
            record_close(symbol, "fast_sl", final_pnl, fills["qty"] or qty,
                         entry, exit_p, side, fee=fills["commission"])
            pos_data["closed"] = True
            changed = True

            loss_amount = abs(final_pnl)
            if loss_amount > FAST_HEAVY_LOSS:
                print(f"  [快捞] 大亏损 {final_pnl:+.2f} USDT（>{FAST_HEAVY_LOSS}U），长冷却60分钟")
                _set_cooling(symbol, FAST_HEAVY_COOLING_SEC)
            else:
                _set_cooling(symbol, FAST_COOLING_SEC)
            print(f"  [快捞] 止损平仓 {symbol} 亏损 {final_pnl:+.2f} USDT")
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
            exit_p = fills["avg_price"] if fills["avg_price"] > 0 else price
            final_pnl = fills["realized_pnl"] if fills["qty"] > 0 else _calc_pnl(price, entry, qty, side)
            record_close(symbol, "fast_tp_lock", final_pnl, fills["qty"] or qty,
                         entry, exit_p, side, fee=fills["commission"])
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

    # 冷却检查
    if _is_cooling(symbol):
        return

    change = (current_price - prev_price) / prev_price
    if change < FAST_TRIGGER_RATIO:
        return

    state = _load_state()
    if _has_position(state, symbol):
        return

    # K线趋势过滤：做多仅up趋势
    if not _check_kline_trend(symbol, want_long=True):
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
                    order_id=order_data.order_id if order_data else 0)
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

    # 冷却检查
    if _is_cooling(symbol):
        return

    change = (current_price - prev_price) / prev_price
    if change > -FAST_TRIGGER_RATIO:
        return

    state = _load_state()
    if _has_position(state, symbol):
        return

    # K线趋势过滤：做空仅down趋势
    if not _check_kline_trend(symbol, want_long=False):
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
                    order_id=order_data.order_id if order_data else 0)
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
