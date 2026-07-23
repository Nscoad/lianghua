"""
币安 API 交易执行层 — 下单、平仓、止损
"""
import hashlib
import hmac
import time
import urllib.parse
import requests as _requests
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NewOrderSideEnum,
    NewOrderTypeEnum,
)
from config import get_futures_config
from core.client import _rate_limit, _handle_api_error, _TIME_OFFSET
from core.queries import get_position, get_fills_agg, get_current_price, _get_symbol_limits


def _calc_slippage(side: str, expected: float | None, actual: float, qty: float) -> float:
    """计算市价单滑点成本（USDT），始终>=0 表示对交易者的不利偏差"""
    if not expected or expected <= 0 or actual <= 0 or qty <= 0:
        return 0.0
    if side in ("BUY", "SELL"):
        # BUY=开多/平空：实际价比预期价高则有滑点
        # SELL=开空/平多：实际价比预期价低则有滑点
        diff = (actual - expected) if side == "BUY" else (expected - actual)
        return round(max(0.0, diff * qty), 4)
    return 0.0


def set_leverage(symbol: str, leverage: int):
    from core.client import client
    try:
        _rate_limit()
        resp = client.rest_api.change_initial_leverage(symbol=symbol, leverage=leverage)
        data = resp.data()
        print(f"杠杆已成功设为 {data.leverage}x")
        return data
    except Exception as e:
        if _handle_api_error(e, "设置杠杆") is True:
            return set_leverage(symbol, leverage)
        return None


def place_market_order(symbol: str, side: str, quantity: float):
    from core.client import client
    try:
        # 记录下单前的行情价（用于计算滑点）
        expected_price = get_current_price(symbol)

        _t0 = time.perf_counter()
        _rate_limit()
        resp = client.rest_api.new_order(
            symbol=symbol,
            side=NewOrderSideEnum(side),
            type=NewOrderTypeEnum.MARKET,
            quantity=quantity,
        )
        data = resp.data()
        order_id = data.order_id
        _elapsed = int((time.perf_counter() - _t0) * 1000)
        print(f"合约下单成功！订单ID: {order_id} (耗时 {_elapsed}ms)")

        # 从交易所获取真实成交数据
        time.sleep(0.3)
        fills = get_fills_agg(symbol, order_id)
        if fills["qty"] > 0:
            print(f"  成交: {fills['qty']:.0f} @ {fills['avg_price']:.8f}")
            print(f"  手续费: {fills['commission']:.4f} USDT")
            print(f"  已实现盈亏: {fills['realized_pnl']:+.2f} USDT")
            # 计算滑点（USDT，始终>=0，表示对交易者的不利偏差）
            fills["slippage"] = _calc_slippage(side, expected_price, fills["avg_price"], fills["qty"])
            if fills["slippage"] > 0:
                print(f"  滑点: {fills['slippage']:.4f} USDT")
        else:
            print("  ⚠ 暂未查到成交明细，使用订单返回的估算数据")
            fills["slippage"] = 0.0

        return data, fills
    except Exception as e:
        if _handle_api_error(e, "合约下单") is True:
            return place_market_order(symbol, side, quantity)
        error_msg = str(e)
        print(f"合约下单失败: {error_msg}")
        try:
            from ai.analyzer import analyze_order_error
            analyze_order_error(symbol, side, quantity, error_msg)
        except Exception:
            pass
        empty = {"qty": 0.0, "avg_price": 0.0, "commission": 0.0, "realized_pnl": 0.0, "slippage": 0.0}
        return None, empty


def place_stop_loss_order(symbol: str, side: str, quantity: float, entry_price: float, stop_loss_ratio: float = 0.15):
    """
    设置服务器端止损单（STOP_MARKET）
    即使程序崩溃/断网，币安服务器也会自动执行止损。
    """
    if entry_price <= 0:
        print("[止损] 无效开仓价，跳过")
        return None

    stop_price = round(entry_price * (1 - stop_loss_ratio) if side == "SELL" else entry_price * (1 + stop_loss_ratio), 8)
    cfg = get_futures_config()
    api_key = cfg["api_key"]
    api_secret = cfg["api_secret"]
    base_url = cfg["base_url"]

    params = {
        "symbol": symbol,
        "side": side,
        "type": "STOP_MARKET",
        "quantity": quantity,
        "stopPrice": stop_price,
        "reduceOnly": "true",
        "timestamp": int((time.time() + _TIME_OFFSET) * 1000),
    }

    query = urllib.parse.urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature

    try:
        resp = _requests.post(
            f"{base_url}/fapi/v1/order",
            headers={"X-MBX-APIKEY": api_key},
            params=params,
            timeout=10,
        )
        data = resp.json()
        if resp.status_code == 200:
            print(f"[止损] 服务器止损单已设置: {symbol} {side} @ {stop_price} (订单ID: {data.get('orderId')})")
            return data
        else:
            if data.get("code") in (-4120, -5000, -2011):
                print("[止损] 当前环境不支持服务器止损（测试网限制），本地风控会接管")
                return None
            print(f"[止损] 设置失败: {data}")
            return None
    except Exception as e:
        print(f"[止损] 请求异常: {e}")
        return None


def close_position(symbol: str = "BTCUSDT"):
    """平仓，返回 (order_data, fills_agg)"""
    empty = {"qty": 0.0, "avg_price": 0.0, "commission": 0.0, "realized_pnl": 0.0, "slippage": 0.0}
    try:
        pos = get_position(symbol)
        if not pos:
            print("当前无持仓，无需平仓。")
            return None, empty
        qty = abs(float(pos["position_amt"]))
        side = "SELL" if float(pos["position_amt"]) > 0 else "BUY"
        direction = "多" if side == "SELL" else "空"

        # 检查交易所单笔限额，超限时拆单
        limits = _get_symbol_limits(symbol)
        close_qty = int(min(qty, int(limits.get("max_qty", 10_000_000_000))))
        orig_qty = qty

        if close_qty < qty:
            print(f"平仓: {symbol} {direction} {qty} -> 单笔限额，分批平仓({close_qty})")
        else:
            print(f"平仓: {symbol} {direction} {qty}")

        # 自动减量重试：超额失败时逐次减少10%
        for attempt in range(5):
            order_data, fills = place_market_order(symbol=symbol, side=side, quantity=close_qty)
            if order_data:
                if close_qty < orig_qty and fills.get("qty", 0) < orig_qty:
                    remaining = orig_qty - (fills["qty"] or close_qty)
                    print(f"  [分批] 剩余 {remaining:.0f}，继续平仓...")
                    close_qty = int(min(remaining, int(limits.get("max_qty", 10_000_000_000))))
                    continue
                return order_data, fills
            close_qty = int(close_qty * 0.9)
            if close_qty < 1:
                break
            print(f"  [重试] 减量至 {close_qty} 重新平仓...")
        return None, empty
    except Exception as e:
        if _handle_api_error(e, "平仓") is True:
            return close_position(symbol)
        error_msg = str(e)
        print(f"平仓失败: {error_msg}")
        try:
            from ai.analyzer import analyze_order_error
            analyze_order_error(symbol, "close", 0, error_msg)
        except Exception:
            pass
        return None, empty
