"""
策略层 — 根据 AI 信号开平仓（不含风险管理）
"""
from datetime import datetime
import time
from core.trader import (
    check_balance, get_current_price, get_position,
    set_leverage, close_position, place_market_order,
    place_stop_loss_order, client, has_open_position,
)
from utils.data_manager import get_latest_signal
from utils.trade_records import record_close, record_open
from utils.historical_data import check_kline_entry_main, check_kline_entry
from strategy.risk_manager import load_risk_state, reset_risk_state, clear_risk_state, is_cooling
from strategy.dual_confirm import check_dual_confirmation
from utils.market_screener import get_dynamic_candidates

DEFAULT_SYMBOL = "BANKUSDT"
LEVERAGE = 5
MARGIN_RATIO = 0.2


def get_symbol_limits(symbol: str) -> dict:
    limits = {"min_qty": 1, "max_qty": 10_000_000_000, "step_size": 1, "min_notional": 0, "tick_size": 0}
    try:
        resp = client.rest_api.exchange_information()
        for s in resp.data().symbols:
            if s.symbol == symbol:
                for f in s.filters:
                    if hasattr(f, "filter_type"):
                        if f.filter_type == "LOT_SIZE":
                            limits["min_qty"] = float(f.min_qty)
                            limits["max_qty"] = min(float(f.max_qty), limits["max_qty"])
                            limits["step_size"] = float(f.step_size)
                        elif f.filter_type == "MARKET_LOT_SIZE":
                            limits["min_qty"] = max(float(f.min_qty), limits["min_qty"])
                            limits["max_qty"] = min(float(f.max_qty), limits["max_qty"])
                            limits["step_size"] = max(float(f.step_size), limits["step_size"])
                break
    except Exception:
        pass
    return limits


def calc_quantity_from_margin(price: float, margin: float, symbol: str = "") -> int:
    position_value = margin * LEVERAGE
    qty = max(int(position_value / price), 1)
    if symbol:
        limits = get_symbol_limits(symbol)
        step = limits["step_size"]
        if step > 0:
            qty = int(qty / step) * step
        qty = min(max(int(qty), int(limits["min_qty"])), int(limits["max_qty"]))
    return max(qty, 1)


def get_current_holding_symbol() -> str | None:
    """从 risk_state 读取持仓币种，并验证交易所确实有该持仓"""
    state = load_risk_state()
    symbol = state.get("symbol") if state else None
    if not symbol:
        return None
    # 验证交易所实际持仓
    pos = get_position(symbol)
    if not pos or float(pos["position_amt"]) == 0:
        clear_risk_state()
        return None
    return symbol


def execute_signal(signal: dict | None) -> dict:
    result = {
        "time": datetime.now().isoformat(),
        "signal_action": None, "signal_symbol": None,
        "executed_action": None, "reason": "",
    }

    target_symbol = DEFAULT_SYMBOL
    action = "hold"
    confidence = 0

    if signal:
        target_symbol = signal.get("symbol", DEFAULT_SYMBOL)
        action = signal.get("action", "hold")
        confidence = signal.get("confidence", 0)
        result["signal_action"] = action
        result["signal_symbol"] = target_symbol

    current_symbol = get_current_holding_symbol()
    has_position = current_symbol is not None

    # 币种切换
    if current_symbol and current_symbol != target_symbol:
        print(f"\n币种切换: {current_symbol} -> {target_symbol}")
        old_pos = get_position(current_symbol)
        if old_pos:
            entry_old = float(old_pos["entry_price"])
            pnl_old = float(old_pos["un_realized_profit"])
            qty_old = abs(float(old_pos["position_amt"]))
            side_old = "LONG" if float(old_pos["position_amt"]) > 0 else "SHORT"
            _, fills = close_position(current_symbol)
            exit_old = fills["avg_price"] if fills["avg_price"] > 0 else float(old_pos.get("mark_price", entry_old))
            record_close(current_symbol, "switch",
                         fills["realized_pnl"] if fills["qty"] > 0 else pnl_old,
                         fills["qty"] if fills["qty"] > 0 else qty_old,
                         entry_old, exit_old, side_old, fee=fills["commission"])
            clear_risk_state()
        else:
            close_position(current_symbol)
            clear_risk_state()
        current_symbol = None
        has_position = False

    if not signal or confidence < 30:
        result["reason"] = "无信号" if not signal else f"信心不足 ({confidence}%)"
        return result

    # K线趋势检查：做多做空都必须与趋势一致
    if action in ("buy", "sell"):
        from utils.historical_data import check_kline_entry
        want_long = (action == "buy")
        kline = check_kline_entry(target_symbol, want_long=want_long)
        trend = kline.get("trend", "sideways")
        if want_long:
            if trend != "up":
                print(f"  [做多过滤] {target_symbol} K线趋势={trend}，非上涨趋势，跳过做多")
                result["executed_action"] = "hold"
                result["reason"] = f"做多限制：{target_symbol} K线{trend}，非上涨趋势"
                return result
            print(f"  [做多通过] {target_symbol} K线趋势向上，允许做多")
        else:
            if trend != "down":
                print(f"  [做空过滤] {target_symbol} K线趋势={trend}，非下跌趋势，跳过做空")
                result["executed_action"] = "hold"
                result["reason"] = f"做空限制：{target_symbol} K线{trend}，非下跌趋势"
                return result
            print(f"  [做空通过] {target_symbol} K线趋势向下，允许做空")

    pos = get_position(target_symbol)
    pos_amt = float(pos["position_amt"]) if pos else 0
    price = get_current_price(target_symbol)
    if not price:
        result["reason"] = "获取价格失败"
        return result

    if pos_amt == 0 and has_open_position():
        result["executed_action"] = "hold"
        result["reason"] = "交易所已有持仓，不重复开仓"
        return result

    print(f"\n信号: {target_symbol} {action} (信心 {confidence}%)")

    if action in ("buy", "sell"):
        want_long = (action == "buy")

        if (want_long and pos_amt > 0) or (not want_long and pos_amt < 0):
            result["executed_action"] = "hold"
            result["reason"] = f"信号{action}，方向一致，持有"
            return result

        # 方向反转
        if pos_amt != 0:
            entry_price = float(pos["entry_price"])
            close_pnl = float(pos["un_realized_profit"])
            side_str = "LONG" if pos_amt > 0 else "SHORT"
            qty_pos = abs(float(pos["position_amt"]))
            pnl_ratio = close_pnl / (qty_pos * entry_price / LEVERAGE) if (qty_pos * entry_price) > 0 else 0
            if pnl_ratio <= -0.20:
                result["executed_action"] = "hold"
                result["reason"] = f"方向反转但已亏{pnl_ratio*100:.0f}%，交给止损处理"
                return result
            _, fills = close_position(target_symbol)
            exit_price = fills["avg_price"] if fills["avg_price"] > 0 else float(pos.get("mark_price", entry_price))
            record_close(target_symbol, "direction_reverse",
                         fills["realized_pnl"] if fills["qty"] > 0 else close_pnl,
                         fills["qty"] if fills["qty"] > 0 else qty_pos,
                         entry_price, exit_price, side_str, fee=fills["commission"])
            clear_risk_state()
            result["executed_action"] = "close"
            result["reason"] = f"方向反转，平仓 {target_symbol}"
            return result

        if has_position:
            result["executed_action"] = "hold"
            result["reason"] = "纪律A：已有持仓，禁止开新单"
            return result

        from utils.data_manager import get_active_feed_count
        if get_active_feed_count(hours=1) < 3:
            result["executed_action"] = "hold"
            result["reason"] = "消息来源不足（过去1h < 3条动态），跳过开仓"
            return result

        # 冷却双确认
        if is_cooling():
            print("\n  --- 冷却状态：检查双确认信号 ---")
            dc = check_dual_confirmation(target_symbol, want_long)
            print(f"  [双确认] {dc['reason']}")
            if not dc["passed"]:
                result["executed_action"] = "hold"
                result["reason"] = f"纪律C：冷却中，双确认未通过: {dc['reason']}"
                return result
            print("  [冷却] 双确认通过，允许开仓")

        # 计算开仓
        balance = check_balance()
        margin = balance * MARGIN_RATIO
        if margin <= 0:
            result["reason"] = "余额不足"
            return result

        print(f"  余额: {balance:.2f} USDT, 开仓20%: {margin:.2f} USDT")
        print(f"  止损(40%保证金={margin*0.40:.2f} USDT = {balance*0.08:.2f} USDT = 8%余额)")
        print(f"  5x杠杆仓位价值: {margin*5:.2f} USDT")

        # 信号确认延迟
        signal_price = price
        print(f"  信号价: {signal_price:.6f}, 等待30秒确认...")
        time.sleep(30)
        confirm_price = get_current_price(target_symbol)
        if not confirm_price:
            result["reason"] = "确认阶段获取价格失败"
            return result

        price = confirm_price
        price_change = (price - signal_price) / signal_price * 100
        print(f"  确认价: {price:.6f} (变化: {price_change:+.2f}%)")

        if (want_long and price_change < -5.0) or (not want_long and price_change > 5.0):
            result["reason"] = f"确认延迟后价格波动{price_change:.1f}%，跳过开仓"
            return result

        # K线入场分析
        print("\n  --- K线入场分析 ---")
        candidates = get_dynamic_candidates(top_n=5)
        if target_symbol not in candidates:
            candidates.insert(0, target_symbol)
        kline_result = check_kline_entry_main(target_symbol, want_long, candidates=candidates)
        if kline_result["decision"] != "enter":
            result["executed_action"] = "hold"
            result["reason"] = f"K线未确认({kline_result['reason']})，等待下轮"
            return result

        if kline_result["symbol"] != target_symbol:
            print(f"  [K线] 切换目标币种: {target_symbol} -> {kline_result['symbol']}")
            target_symbol = kline_result["symbol"]
            price = get_current_price(target_symbol)
            if not price:
                result["reason"] = "换币后获取价格失败"
                return result

        qty = calc_quantity_from_margin(price, margin, symbol=target_symbol)
        notional = qty * price
        print(f"  数量: {qty} (名义价值: {notional:.2f} USDT)")

        # ====== 下单前最终检查：防止并发重复开仓 ======
        final_pos = get_position(target_symbol)
        if final_pos:
            final_amt = float(final_pos["position_amt"])
            if final_amt != 0:
                result["executed_action"] = "hold"
                result["reason"] = f"重复开仓防护：{target_symbol} 交易所已有仓位({final_amt})，跳过"
                print(f"  [防护] 检测到 {target_symbol} 已有仓位，防止重复开仓")
                return result
        side = "BUY" if want_long else "SELL"
        set_leverage(target_symbol, LEVERAGE)
        order_data, fills = place_market_order(symbol=target_symbol, side=side, quantity=qty)

        if order_data:
            reset_risk_state(target_symbol, margin)
            result["executed_action"] = f"open_{'long' if want_long else 'short'}"
            result["reason"] = f"{target_symbol} 开{'多' if want_long else '空'} {qty}"
            record_open(target_symbol, "LONG" if want_long else "SHORT", fills["qty"] or qty,
                        fills["avg_price"] or price, fee=fills["commission"],
                        order_id=order_data.order_id if order_data else 0)
            place_stop_loss_order(symbol=target_symbol, side="SELL" if want_long else "BUY",
                                  quantity=qty, entry_price=price, stop_loss_ratio=0.40)
        else:
            result["reason"] = "开仓失败"
    else:
        result["executed_action"] = "hold"
        result["reason"] = "信号建议持有"

    return result


def run_auto_trade():
    print("\n" + "=" * 50)
    print("  AI 交易信号执行")
    print("=" * 50)
    signal = get_latest_signal()
    result = execute_signal(signal)
    if result.get("signal_symbol"):
        print(f"信号币种: {result['signal_symbol']}", end="")
    if result.get("signal_action"):
        print(f" 操作: {result['signal_action']}", end="")
    print(f"\n执行结果: {result['executed_action']} — {result['reason']}")
    return result
