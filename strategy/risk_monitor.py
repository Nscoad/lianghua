"""
风险监控 — 高频执行（每3秒一次）

基于1:3盈亏比的止盈策略：
  阶段            触发条件                       操作
  ─────────────────────────────────────────────────────────────
  止损 (SL)      亏损 ≥ 15% 保证金              全平，冷却
  TP1 (首轮止盈)  盈利 ≥ 45% 保证金 (3×止损)      平50%，止损移至保本
  保本止损        价格回到开仓价                  全平（盈亏比保底1:1.5）
  3根K线无方向    最近3根1hK线无明显趋势           全平（不耗时间）
  盘整区全平      整体盘整，不给趋势空间            全平（不确定性离场）
  趋势反转        K线趋势与持仓相反                全平（不逆势）
  趋势延续        方向正确，无以上条件              持有吃大行情
"""

import time as _time
from core.trader import get_current_price, get_position, close_position, place_market_order
from strategy.risk_manager import load_risk_state, save_risk_state, clear_risk_state, exit_cooling
from utils.trade_records import record_close
from utils.historical_data import get_kline_levels

LEVERAGE = 5
STOP_LOSS_RATIO = -0.15         # 止损：亏15%保证金就割
TP_RATIO = 0.45                 # 止盈：赚45%保证金（3×止损，1:3盈亏比）
TP1_CLOSE_RATIO = 0.50          # TP1平半仓


def _close_all(symbol: str, reason: str, qty: float, entry_price: float,
               current_price: float, is_long: bool, state: dict):
    """全平并清理状态"""
    _, fills = close_position(symbol)
    exit_price = fills["avg_price"] or current_price
    side_label = "LONG" if is_long else "SHORT"
    pnl = fills["realized_pnl"] or ((exit_price - entry_price) * qty if is_long else (entry_price - exit_price) * qty)
    record_close(symbol, reason, pnl, fills["qty"] or qty,
                 entry_price, exit_price, side_label, fee=fills["commission"])
    clear_risk_state()
    return reason


def check_risk_once(silent: bool = True) -> str:
    state = load_risk_state()
    symbol = state.get("symbol", "")
    if not symbol:
        return "no_position"

    pos = get_position(symbol)
    if not pos:
        clear_risk_state()
        return "no_position"

    pos_amt = float(pos["position_amt"])
    entry_price = float(pos["entry_price"])
    current_price = float(pos["mark_price"]) if "mark_price" in pos else get_current_price(symbol)
    if not current_price:
        return "price_error"

    is_long = pos_amt > 0
    qty = abs(float(pos_amt))
    unrealized_pnl = (current_price - entry_price) * qty if is_long else (entry_price - current_price) * qty
    current_margin_calc = qty * entry_price / LEVERAGE
    base_margin = state.get("current_margin", current_margin_calc)
    pnl_ratio = unrealized_pnl / base_margin if base_margin > 0 else 0

    # 微型仓位平仓
    if base_margin < 5.0:
        print(f"\n[风控] 微型仓位平仓! {symbol} 保证金仅 {base_margin:.2f} USDT")
        return _close_all(symbol, "micro_close", qty, entry_price, current_price, is_long, state)

    # ===== 初始小止损（始终有效） =====
    if pnl_ratio <= STOP_LOSS_RATIO:
        print(f"\n[风险] 小止损触发! {symbol} {pnl_ratio*100:.1f}%")
        return _close_all(symbol, "stop_loss", qty, entry_price, current_price, is_long, state)

    # ===== K线关键位分析（供防耗散/盘整/趋势反转使用） =====
    levels = get_kline_levels(symbol)
    if not levels:
        return "holding"

    trend = levels["trend"]

    # ===== TP1 已触发：保本止损 + 安全阀 =====
    if state.get("tp_done"):
        # 1. 保本检查：价格回到开仓价 → 平仓（保底盈亏比1:1.5）
        if (is_long and current_price <= entry_price * 1.001) or \
           (not is_long and current_price >= entry_price * 0.999):
            print(f"\n[保本止损] {symbol} 回到开仓价 {entry_price:.6f}，落袋")
            return _close_all(symbol, "breakeven_close", qty, entry_price, current_price, is_long, state)

        # 2. 盘整检查
        if levels["is_consolidating"]:
            print(f"\n[盘整全平] {symbol} 盘整区: {levels['consolidation_reason']}")
            return _close_all(symbol, "consolidation_close", qty, entry_price, current_price, is_long, state)

        # 3. 3根K线无方向检查
        if levels["bars_no_direction"] >= 2:
            print(f"\n[3根K线无方向] {symbol} {levels['bars_no_direction']}/3根，平仓")
            return _close_all(symbol, "no_direction_close", qty, entry_price, current_price, is_long, state)

        # 4. 趋势反转检查
        if (is_long and trend == "down") or (not is_long and trend == "up"):
            print(f"\n[趋势反转] {symbol} K线趋势={trend}，与持仓方向相反，平仓")
            return _close_all(symbol, "trend_reversal_close", qty, entry_price, current_price, is_long, state)

        # 5. 一切正常 → 持有
        return "holding"

    # ===== TP1 尚未触发：1:3盈亏比止盈检查 =====
    # 止损15%保证金 ≈ 价格反向3%（5x杠杆下）
    # 止盈 = 3×止损距离 = 45%保证金 ≈ 价格正向9%
    if pnl_ratio >= TP_RATIO:
        reduce_qty = int(qty * TP1_CLOSE_RATIO)
        if reduce_qty >= 1 and reduce_qty < qty:
            side = "SELL" if is_long else "BUY"
            tp1_pct = pnl_ratio * 100
            print(f"\n[TP1首轮止盈] {symbol} 浮盈+{tp1_pct:.1f}%保证金，平半仓 {reduce_qty}，止损移至保本")
            _, fills = place_market_order(symbol=symbol, side=side, quantity=reduce_qty)
            exit_tp = fills["avg_price"] or current_price
            reduce_pnl = fills["realized_pnl"] or (unrealized_pnl * (reduce_qty / qty))
            record_close(symbol, "tp1_rr", reduce_pnl, fills["qty"] or reduce_qty,
                         entry_price, exit_tp, "LONG" if is_long else "SHORT",
                         is_partial=True, fee=fills["commission"])

            state["tp_done"] = True
            remaining_margin = current_margin_calc * (1 - TP1_CLOSE_RATIO)
            state["current_margin"] = remaining_margin
            exit_cooling()
            save_risk_state(state)
            return "tp1_rr"
        else:
            # 数量太小无法减半 → 直接全平
            print(f"\n[TP1] {symbol} 数量 {qty} 太小无法减半，直接全平")
            return _close_all(symbol, "tp1_full_close", qty, entry_price, current_price, is_long, state)

    return "holding"


def get_current_pnl_data(symbol: str) -> dict | None:
    pos = get_position(symbol)
    if not pos:
        return None
    state = load_risk_state()
    pos_amt = float(pos["position_amt"])
    entry_price = float(pos["entry_price"])
    current_price = float(pos["mark_price"]) if "mark_price" in pos else get_current_price(symbol)
    if not current_price:
        return None
    is_long = pos_amt > 0
    qty = abs(float(pos_amt))
    unrealized_pnl = (current_price - entry_price) * qty if is_long else (entry_price - current_price) * qty
    base_margin = state.get("current_margin", state.get("original_margin", 0))
    return {
        "symbol": symbol, "position_amt": pos_amt, "entry_price": entry_price,
        "current_price": current_price, "unrealized_pnl": round(unrealized_pnl, 2),
        "pnl_ratio": round(unrealized_pnl / base_margin * 100, 2) if base_margin > 0 else 0,
        "base_margin": round(base_margin, 2), "tp_done": state.get("tp_done", False),
    }
