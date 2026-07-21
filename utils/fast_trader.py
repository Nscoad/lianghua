"""
快速捞钱交易 — 独立于主仓的小仓位快速买卖

监测所有币种每2分钟的价格变化，15分钟涨幅>6%时做多、跌幅>6%时做空，
各使用5%余额+5x杠杆。
浮动利润锁仓：盈利达+10%设锁仓线+2%，达+15%提升到+4%，回撤到线就平。
止损-1.5%始终有效。

风险机制：
  - 冷却机制：止损后同币种15分钟内不再触发
  - K线趋势过滤：做多仅trend=up，做空仅trend=down
  - 大亏损长冷却：单笔止损>20U时，冷却延长至60分钟
"""
import json
import os
import time
from datetime import datetime
from core.trader import check_balance, get_current_price, place_market_order, set_leverage, close_position
from utils.trade_records import record_open, record_close

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
STATE_FILE = os.path.join(DATA_DIR, "fast_trade_state.json")

FAST_LEVERAGE = 5
FAST_MARGIN_RATIO = 0.05       # 5% 余额
FAST_SL_RATIO = -0.015         # 止损 -1.5%
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
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def _has_position(state: dict) -> bool:
    return bool(state.get("symbol") and not state.get("closed", False))


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
        from utils.historical_data import check_kline_entry
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

def check_fast_position():
    """
    检查快仓位是否需要止损/浮动锁仓平仓。

    浮动利润锁仓逻辑：
      1. 止损 -1.5% → 全平 + 冷却
      2. 盈利达 +10% → 设锁仓线 +2%（回撤到+2%就平）
      3. 盈利达 +15% → 提升锁仓线到 +4%
      4. 一直涨就一直拿，逐步扩大利润
    """
    state = _load_state()
    if not _has_position(state):
        return False

    symbol = state["symbol"]
    entry = state["entry_price"]
    side = state["side"]
    qty = state["qty"]

    price = get_current_price(symbol)
    if not price:
        return False

    pnl_ratio = (price - entry) / entry if side == "LONG" else (entry - price) / entry

    # === 止损（始终有效） ===
    if pnl_ratio <= FAST_SL_RATIO:
        print(f"\n[快捞] 止损触发! {symbol} {pnl_ratio*100:.1f}%")
        _, fills = close_position(symbol)
        exit_p = fills["avg_price"] if fills["avg_price"] > 0 else price
        final_pnl = fills["realized_pnl"] if fills["qty"] > 0 else _calc_pnl(price, entry, qty, side)
        record_close(symbol, "fast_sl", final_pnl, fills["qty"] or qty,
                     entry, exit_p, side, fee=fills["commission"])
        state["closed"] = True
        _save_state(state)

        # 冷却：大亏损 (>20U) 冷却60分钟，否则冷却15分钟
        loss_amount = abs(final_pnl)
        if loss_amount > FAST_HEAVY_LOSS:
            print(f"  [快捞] 大亏损 {final_pnl:+.2f} USDT（>{FAST_HEAVY_LOSS}U），长冷却60分钟")
            _set_cooling(symbol, FAST_HEAVY_COOLING_SEC)
        else:
            _set_cooling(symbol, FAST_COOLING_SEC)
        print(f"  [快捞] 止损平仓 {symbol} 亏损 {final_pnl:+.2f} USDT")
        return True

    # === 浮动利润锁仓 ===
    profit_floor = state.get("profit_floor", 0.0)
    highest = state.get("highest_profit_pct", 0.0)

    # 更新最高盈利 → 动态计算锁仓线
    if pnl_ratio > highest:
        highest = pnl_ratio
        state["highest_profit_pct"] = highest

        # 浮动锁仓：每多5%盈利，锁仓线上移2%
        #   +10%→锁2%，+15%→锁4%，+20%→锁6%，类推
        if highest >= FAST_LOCK_TRIGGER_INIT:
            extra = int((highest - FAST_LOCK_TRIGGER_INIT) / 0.05)  # 超过起始几档5%
            new_floor = FAST_LOCK_FLOOR_INIT + extra * 0.02

            if new_floor != profit_floor:
                profit_floor = new_floor
                print(f"  [快捞] {symbol} 盈利达+{highest*100:.1f}%! 锁仓线提升到+{profit_floor*100:.0f}%")

        state["profit_floor"] = profit_floor
        _save_state(state)

    # 检查盈利是否回撤到锁仓线
    if profit_floor > 0 and pnl_ratio <= profit_floor:
        print(f"\n[快捞] 浮动锁仓触发! {symbol} {pnl_ratio*100:.2f}% <= 锁仓线+{profit_floor*100:.0f}%")
        _, fills = close_position(symbol)
        exit_p = fills["avg_price"] if fills["avg_price"] > 0 else price
        final_pnl = fills["realized_pnl"] if fills["qty"] > 0 else _calc_pnl(price, entry, qty, side)
        record_close(symbol, "fast_tp_lock", final_pnl, fills["qty"] or qty,
                     entry, exit_p, side, fee=fills["commission"])
        state["closed"] = True
        _save_state(state)
        print(f"  [快捞] 浮动锁仓平仓 {symbol} 盈利 {final_pnl:+.2f} USDT")
        return True

    return False


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
    if _has_position(state):
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
    print(f"  余额 {balance:.2f} USDT, 开仓5% = {margin:.2f} USDT, 数量 {qty}")
    set_leverage(symbol, FAST_LEVERAGE)
    order_data, fills = place_market_order(symbol=symbol, side="BUY", quantity=qty)

    if order_data:
        actual_qty = fills["qty"] or qty
        actual_price = fills["avg_price"] or current_price
        record_open(symbol, "LONG", actual_qty, actual_price, fee=fills["commission"],
                    order_id=order_data.order_id if order_data else 0)
        _save_state({
            "symbol": symbol,
            "entry_price": actual_price,
            "side": "LONG",
            "qty": actual_qty,
            "margin": margin,
            "open_time": datetime.now().isoformat(),
            "closed": False,
            "profit_floor": 0.0,
            "highest_profit_pct": 0.0,
        })
        print(f"  [快捞] {symbol} 开仓成功 @ {actual_price}")
        print(f"  [策略] +10%启动锁仓(+2%) → 每+5%锁仓+2% | 止损-1.5%")
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
    if _has_position(state):
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
    print(f"  余额 {balance:.2f} USDT, 开仓5% = {margin:.2f} USDT, 数量 {qty}")
    set_leverage(symbol, FAST_LEVERAGE)
    order_data, fills = place_market_order(symbol=symbol, side="SELL", quantity=qty)

    if order_data:
        actual_qty = fills["qty"] or qty
        actual_price = fills["avg_price"] or current_price
        record_open(symbol, "SHORT", actual_qty, actual_price, fee=fills["commission"],
                    order_id=order_data.order_id if order_data else 0)
        _save_state({
            "symbol": symbol,
            "entry_price": actual_price,
            "side": "SHORT",
            "qty": actual_qty,
            "margin": margin,
            "open_time": datetime.now().isoformat(),
            "closed": False,
            "profit_floor": 0.0,
            "highest_profit_pct": 0.0,
        })
        print(f"  [快捞] {symbol} 做空成功 @ {actual_price}")
        print(f"  [策略] +10%启动锁仓(+2%) → 每+5%锁仓+2% | 止损-1.5%")
    else:
        print(f"  [快捞] {symbol} 做空失败")
