"""
快速捞钱交易 — 独立于主仓的小仓位快速买卖

监测所有币种每1分钟的价格变化，15分钟涨幅>7.3%时做多、跌幅>7.3%时做空，
各使用10%余额+5x杠杆。
浮动利润锁仓：盈利达+10%设锁仓线+2%，达+15%提升到+4%，回撤到线就平。
止损-1.5%始终有效。

风险机制：
  - 冷却机制：止损后同币种10分钟内不再触发，不再提前解除
  - K线趋势过滤：做多仅trend=up，做空仅trend=down
  - 逆势检测：K线方向与开仓方向相反时，触发门槛从7.3%提高到10%
  - 高波动币种止损放宽：24h振幅>20%的币种止损从-1.5%放宽到-2.5%
  - 大亏损长冷却：单笔止损>20U时，冷却延长至10分钟
  - 时间段限制：00~06和12~15禁掉，06~09全开，09~12仅做多，15~18门槛10%
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
FAST_TRIGGER_RATIO = 0.073    # 触发门槛：15分钟涨跌幅度 >7.3%
# 浮动利润锁仓参数
FAST_LOCK_TRIGGER_INIT = 0.10  # 起始触发：盈利达+10%
FAST_LOCK_FLOOR_INIT = 0.04    # 起始锁仓线：+4%
# 之后每多5%盈利，锁仓线上移2%（+15%→锁6%，+20%→锁8%，以此类推）
FAST_MIN_VOLUME = 500_000      # 最低成交额 50万U

# 冷却参数
FAST_COOLING_SEC = 600          # 止损后冷却10分钟
FAST_HEAVY_LOSS = 20            # 单笔亏损>20U视为大亏损
FAST_HEAVY_COOLING_SEC = 600    # 大亏损也冷却10分钟

# 逆势监测参数
FAST_CONTRARIAN_THRESHOLD = 0.10    # K线方向与开仓相反时，触发门槛提高到10%
FAST_HIGH_VOL_THRESHOLD = 0.20     # 24h振幅>20%视为高波动币种
FAST_HIGH_VOL_SL_RATIO = -0.125    # 高波动币种止损 -12.5%（保证金回报率，对应价格 -2.5% × 5x）

# 滚仓参数
FAST_ROLL_PROFIT_RATIO = 0.25    # 每次拿盈利的25%加仓
FAST_ROLL_INTERVAL = 1.0         # 每多赚100%（保证金回报率），滚仓一次

# ---- 内存状态缓存：消除每5秒SQLite全表扫描 ----
# save 时直接更新缓存，load 时优先返回缓存（最多滞后1次save周期）
_state_cache: dict | None = None
_state_cache_time: float = 0.0
_STATE_CACHE_TTL = 1.0  # 秒，兜底TTL防止极端情况下的无限旧数据

# ---- 打印限流 ----
_last_floor_print: dict[str, float] = {}
_last_vol_print: dict[str, float] = {}
_last_vol_amp: dict[str, float] = {}   # 上次打印时的振幅值
_VOL_REPRINT_DIFF = 0.10               # 振幅变化超过10个百分点才重打


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

def _is_cooling(symbol: str) -> bool:
    """检查该币种是否在冷却中。冷却期内不提前解除。"""
    state = _load_state()
    cooling = state.get("cooling", {})
    expires = cooling.get(symbol, 0)
    if time.time() >= expires:
        return False
    remain = int(expires - time.time())
    print(f"  [快捞冷却] {symbol} 冷却中，剩余 {remain//60}分{remain%60}秒")
    return True


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


# ==================== 逆势检测 & 波动率评估 ====================

_LATEST_KLINE_CACHE: dict[str, tuple[float, dict | None]] = {}
_LATEST_KLINE_TTL = 15  # 缓存15秒


def _get_latest_kline(symbol: str) -> dict | None:
    """获取最新一根15分钟K线，带短缓存（15秒）"""
    import time as _t
    now = _t.time()
    cached = _LATEST_KLINE_CACHE.get(symbol)
    if cached and now - cached[0] < _LATEST_KLINE_TTL:
        return cached[1]
    try:
        from utils.market.kline import _fetch_real_klines
        klines = _fetch_real_klines(symbol, limit=1, interval="15m")
        result = klines[-1] if klines else None
        _LATEST_KLINE_CACHE[symbol] = (now, result)
        return result
    except Exception:
        return None


def _is_contrarian_candle(symbol: str, want_long: bool) -> bool:
    """
    判断最新K线是否与开仓方向相反。
    做多时最新K线为阴线(close<open) → 逆势
    做空时最新K线为阳线(close>open) → 逆势
    Returns: True=逆势
    """
    k = _get_latest_kline(symbol)
    if not k:
        return False
    if want_long and k["close"] < k["open"]:
        return True
    if not want_long and k["close"] > k["open"]:
        return True
    return False


def _get_amplitude(symbol: str) -> float:
    """获取该币种最近3小时振幅（12根15分钟K线）"""
    try:
        from utils.market.kline import _fetch_real_klines
        klines = _fetch_real_klines(symbol, limit=12, interval="15m")
        if len(klines) < 6:
            return 0.0
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        max_h = max(highs)
        min_l = min(lows)
        return (max_h - min_l) / min_l
    except Exception:
        return 0.0


def _is_high_volatility(symbol: str) -> bool:
    """判断是否为高波动币种（最近3h振幅 > 20%）"""
    amp = _get_amplitude(symbol)
    if amp > FAST_HIGH_VOL_THRESHOLD:
        now = time.time()
        last_time = _last_vol_print.get(symbol, 0.0)
        last_amp = _last_vol_amp.get(symbol, 0.0)
        # 限流条件：距上次打印 ≥60秒 且 振幅变化 ≥10个百分点
        if now - last_time >= 60 and abs(amp - last_amp) >= _VOL_REPRINT_DIFF:
            _last_vol_print[symbol] = now
            _last_vol_amp[symbol] = amp
            print(f"  [波动率评估] {symbol} 近3h振幅 {amp*100:.0f}% > 20%，视为高波动币种")
        return True
    return False


def _get_dynamic_sl(symbol: str) -> float:
    """
    根据币种波动率返回动态止损线（保证金回报率）。
    高波动币种（近3h振幅>20%）放宽到 -2.5%（-12.5%保证金回报），其余保持 -1.5%（-7.5%）。
    """
    if _is_high_volatility(symbol):
        return FAST_HIGH_VOL_SL_RATIO
    return FAST_SL_RATIO


# ==================== 滚仓（复利加仓） ====================

def _try_roll_position(symbol: str, pos_data: dict, current_price: float, state: dict) -> bool:
    """
    检查并执行滚仓。
    当最高盈利达到 next_roll_pct（每100%一次），拿盈利的25%加仓。
    Returns: True=执行了滚仓
    """
    side = pos_data["side"]
    entry = pos_data["entry_price"]
    qty = pos_data["qty"]
    highest = pos_data.get("highest_profit_pct", 0.0)
    next_pct = pos_data.get("next_roll_pct", FAST_ROLL_INTERVAL)

    if highest < next_pct:
        return False

    # 计算当前未实现盈亏（USDT）
    if side == "LONG":
        unrealized_pnl = (current_price - entry) * qty
    else:
        unrealized_pnl = (entry - current_price) * qty

    if unrealized_pnl <= 0:
        return False

    # 拿25%作为追加保证金
    add_margin = unrealized_pnl * FAST_ROLL_PROFIT_RATIO
    add_qty = int(add_margin * FAST_LEVERAGE / current_price)
    if add_qty < 1:
        print(f"  [滚仓] {symbol} 盈利 {unrealized_pnl:+.2f} USDT，但加仓量不足1，跳过")
        pos_data["next_roll_pct"] = next_pct + FAST_ROLL_INTERVAL
        return False

    # 下单加仓（同方向）
    buy_side = "BUY" if side == "LONG" else "SELL"
    order_data, fills = place_market_order(symbol=symbol, side=buy_side, quantity=add_qty)
    if not order_data:
        print(f"  [滚仓] {symbol} 加仓下单失败，跳过")
        return False

    actual_add_qty = fills.get("qty", add_qty) or add_qty
    actual_add_price = fills.get("avg_price", current_price) or current_price

    # 更新加权平均入场价
    total_qty = qty + actual_add_qty
    new_entry = (qty * entry + actual_add_qty * actual_add_price) / total_qty

    pos_data["entry_price"] = new_entry
    pos_data["qty"] = total_qty
    # 追加的保证金也算进 margin
    pos_data["margin"] = pos_data.get("margin", 0) + add_margin
    pos_data["next_roll_pct"] = next_pct + FAST_ROLL_INTERVAL
    pos_data["roll_count"] = pos_data.get("roll_count", 0) + 1

    # 滚仓后重算最高盈利：把旧盈率转成绝对价格，再用新加权均价换算
    # 例如旧入场 1.0 时最高盈 500%（最高到过 2.0），入场变 1.383 后 → 223%
    # 这样 _calc_kline_lock_floor 能基于调整后的值算出合理的止盈线
    old_highest = pos_data.get("highest_profit_pct", 0.0)
    if side == "LONG" and old_highest > 0:
        high_price = entry * (1 + old_highest / FAST_LEVERAGE)
        adjusted = max(0, (high_price - new_entry) / new_entry * FAST_LEVERAGE)
    elif side == "SHORT" and old_highest > 0:
        high_price = entry * (1 - old_highest / FAST_LEVERAGE)
        adjusted = max(0, (new_entry - high_price) / new_entry * FAST_LEVERAGE)
    else:
        adjusted = 0.0
    # 避免调整后的盈率 ≥ next_roll_pct 导致同一个价格水平连续滚仓
    pos_data["highest_profit_pct"] = min(adjusted, next_pct - 0.001)
    # 止盈线归零，让 lock_floor 在下个循环基于调整后的 highest 重新算
    pos_data["profit_floor"] = 0.0

    # 记录滚仓到交易流水（用 open 记录，reason=fast_roll）
    from utils.trade.records import record_open
    record_open(symbol, side, actual_add_qty, actual_add_price,
                fee=fills.get("commission", 0),
                order_id=order_data.order_id if order_data else 0,
                slippage=fills.get("slippage", 0.0),
                entry_mode="roll")

    print(f"  [滚仓] {symbol} 盈利{unrealized_pnl:+.2f}USDT，追加{add_margin:.2f}U保证金(+{actual_add_qty}张@{actual_add_price:.4f})")
    print(f"        加权入场{new_entry:.4f}，总仓位{total_qty}张，下次滚仓+{next_pct+FAST_ROLL_INTERVAL:.0f}%")
    return True


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
    """平仓验证：确认交易所持仓已清空。
    绕过缓存从交易所直接查询，失败后重试一次（交易所状态同步有延迟）。
    返回 True 表示确实平掉了。
    """
    import time as _time
    for attempt in range(2):
        try:
            from core.queries import _cache as _qcache
            # 绕过缓存，直接从交易所查询
            _qcache.pop(f"pos_{symbol}", None)
            pos = get_position(symbol)
            if pos is None:
                return True
            amt = abs(float(pos["position_amt"]))
            if amt < 1:
                return True
            if attempt == 0:
                _time.sleep(1)
                continue
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

        # === 止损（始终有效，高波动币种放宽到-2.5%） ===
        sl_ratio = _get_dynamic_sl(symbol)
        if pnl_ratio <= sl_ratio:
            sl_label = "高波动止损-2.5%" if sl_ratio == FAST_HIGH_VOL_SL_RATIO else "止损-1.5%"
            print(f"\n[快捞] {sl_label} 触发! {symbol} {pnl_ratio*100:.1f}%")
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
                print(f"  [快捞] 大亏损 {final_pnl:+.2f} USDT（>{FAST_HEAVY_LOSS}U），冷却10分钟")
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

        # === 滚仓检查：最高盈利每到100%门槛，拿25%利润加仓 ===
        if _try_roll_position(symbol, pos_data, price, state):
            changed = True
            # 滚仓后加权均价变了，重新读取最新数据避免下面用旧值算错止盈线
            entry = pos_data["entry_price"]
            qty = pos_data["qty"]
            if side == "LONG":
                pnl_ratio = (price - entry) / entry * FAST_LEVERAGE
            else:
                pnl_ratio = (entry - price) / entry * FAST_LEVERAGE
            highest = pos_data.get("highest_profit_pct", 0.0)
            profit_floor = pos_data.get("profit_floor", 0.0)

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


# 时间段交易策略：(hour_start, hour_end, allow_long, allow_short, trigger_boost)
# trigger_boost: 1.0=7.3%, 1.37=10%, 1.64=12%
_TIME_RULES = [
    (0,  6,  True,  True,  1.0),    # 00~06: 美盘尾，全开
    (6,  9,  True,  True,  1.0),    # 06~09: ✅ 黄金时段，全开做空
    (9,  12, True,  False, 1.0),    # 09~12: ✅ 只做多（做空-631U重灾区）
    (12, 18, True,  True,  1.37),   # 12~18: ⚠️ 门槛10%（1.37×7.3%≈10%）
    (18, 21, True,  True,  1.0),    # 18~21: 正常（样本少，先不动）
    (21, 24, True,  True,  1.0),    # 21~00: ✅ 美盘，全开做空
]


def _get_time_policy(want_long: bool) -> dict:
    """根据当前小时返回策略：{allowed, trigger_multiplier, block_reason}"""
    hour = datetime.now().hour
    for start, end, can_long, can_short, boost in _TIME_RULES:
        if start <= hour < end:
            allowed = can_long if want_long else can_short
            reason = None
            if not allowed:
                reason = f"时间段{start:02d}:00~{end:02d}:00 禁止{'做多' if want_long else '做空'}"
            return {"allowed": allowed, "trigger_multiplier": boost, "block_reason": reason}
    return {"allowed": True, "trigger_multiplier": 1.0, "block_reason": None}


def try_fast_open(symbol: str, current_price: float, prev_price: float):
    """尝试快速开仓 — 涨幅达标时买入"""
    _clean_expired_cooling()

    # 时间段限制
    policy = _get_time_policy(want_long=True)
    if not policy["allowed"]:
        print(f"  [快捞] {symbol} {policy['block_reason']}")
        return

    if _is_cooling(symbol):
        return

    change = (current_price - prev_price) / prev_price
    effective_trigger = FAST_TRIGGER_RATIO * policy["trigger_multiplier"]
    if change < effective_trigger:
        return

    state = _load_state()
    if _has_position(state, symbol):
        return

    # K线趋势过滤：做多仅up趋势
    can_enter, entry_mode = _check_kline_trend(symbol, want_long=True)
    if not can_enter:
        return

    # 逆势检测：K线阴线做多 → 逆势，触发门槛取时段倍率和固化的较大值
    if _is_contrarian_candle(symbol, want_long=True):
        contrarian_threshold = max(effective_trigger, FAST_CONTRARIAN_THRESHOLD)
        if change < contrarian_threshold:
            print(f"  [快捞逆势检测] {symbol} K线阴线做多（逆势），涨幅{change*100:.1f}%<{contrarian_threshold*100:.0f}%，跳过")
            return
        print(f"  [快捞逆势检测] {symbol} K线阴线做多（逆势），涨幅{change*100:.1f}%>={contrarian_threshold*100:.0f}%，强制入场")

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
            "next_roll_pct": FAST_ROLL_INTERVAL,  # 到100%触发首次滚仓
            "roll_count": 0,
        }
        _save_state(state)
        print(f"  [快捞] {symbol} 开仓成功 @ {actual_price}")
        print("  [策略] 滚仓:+100%→25%加仓 | 锁仓:+10%启动 | 止损-1.5%")
    else:
        print(f"  [快捞] {symbol} 开仓失败")


def try_fast_short(symbol: str, current_price: float, prev_price: float):
    """尝试快速做空 — 跌幅达标时做空"""
    _clean_expired_cooling()

    # 时间段限制
    policy = _get_time_policy(want_long=False)
    if not policy["allowed"]:
        print(f"  [快捞] {symbol} {policy['block_reason']}")
        return

    if _is_cooling(symbol):
        return

    change = (current_price - prev_price) / prev_price
    effective_trigger = FAST_TRIGGER_RATIO * policy["trigger_multiplier"]
    if change > -effective_trigger:
        return

    state = _load_state()
    if _has_position(state, symbol):
        return

    # K线趋势过滤：做空仅down趋势
    can_enter, entry_mode = _check_kline_trend(symbol, want_long=False)
    if not can_enter:
        return

    # 逆势检测：K线阳线做空 → 逆势，触发门槛取时段倍率和固化的较大值
    if _is_contrarian_candle(symbol, want_long=False):
        contrarian_threshold = max(effective_trigger, FAST_CONTRARIAN_THRESHOLD)
        if abs(change) < contrarian_threshold:
            print(f"  [快捞逆势检测] {symbol} K线阳线做空（逆势），跌幅{abs(change)*100:.1f}%<{contrarian_threshold*100:.0f}%，跳过")
            return
        print(f"  [快捞逆势检测] {symbol} K线阳线做空（逆势），跌幅{abs(change)*100:.1f}%>={contrarian_threshold*100:.0f}%，强制入场")

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
            "next_roll_pct": FAST_ROLL_INTERVAL,  # 到100%触发首次滚仓
            "roll_count": 0,
        }
        _save_state(state)
        print(f"  [快捞] {symbol} 做空成功 @ {actual_price}")
        print("  [策略] 滚仓:+100%→25%加仓 | 锁仓:+10%启动 | 止损-1.5%")
    else:
        print(f"  [快捞] {symbol} 做空失败")
