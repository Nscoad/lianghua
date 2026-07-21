"""
U本位合约 API 执行层 — 行动层
所有合约操作函数，不包含入口逻辑
"""
import time
import urllib.parse
import hashlib
import hmac
import requests as _requests
from binance_common.configuration import ConfigurationRestAPI
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NewOrderSideEnum,
    NewOrderTypeEnum,
)
from config import get_futures_config

_LAST_SYNC = 0
_TIME_OFFSET = 0.0  # 本地时间与币安服务器时间差值（秒），本地慢为正


def _fetch_server_time() -> float:
    """获取币安服务器时间戳（毫秒）"""
    try:
        resp = _requests.get(
            "https://fapi.binance.com/fapi/v1/time",
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200:
            return resp.json()["serverTime"] / 1000.0
    except Exception:
        pass
    return 0


def _sync_system_time():
    """校准本地时间偏移（每60秒限频一次）"""
    global _LAST_SYNC, _TIME_OFFSET
    now = time.time()
    if now - _LAST_SYNC < 60:
        return False
    _LAST_SYNC = now
    try:
        server_ts = _fetch_server_time()
        if server_ts > 0:
            _TIME_OFFSET = server_ts - time.time()
            print(f"[时间同步] 本地与币安服务器时差 {_TIME_OFFSET*1000:.0f}ms")
            if abs(_TIME_OFFSET) > 1:
                print(f"  -> 已记录偏移，后续请求自动补偿")
            return True
        print("[时间同步] 获取服务器时间失败，跳过")
        return False
    except Exception as e:
        print(f"[时间同步] 异常: {e}")
        return False


def _is_timestamp_error(e) -> bool:
    """判断是否为 -1021 时间戳错误"""
    err = str(e)
    return "-1021" in err or "Timestamp" in err


def _recover_client():
    """重新初始化客户端（时间同步后调用）"""
    global client
    client = get_client()


def get_client():
    cfg = get_futures_config()
    config = ConfigurationRestAPI(
        api_key=cfg["api_key"],
        api_secret=cfg["api_secret"],
        base_path=cfg["base_url"],
        compression=False,
        timeout=10000,
    )
    return DerivativesTradingUsdsFutures(config_rest_api=config)


client = get_client()

# 全局API限流：相邻请求至少间隔200ms
_cache: dict = {}
_last_api_time = 0.0


def _rate_limit():
    """确保两次API调用之间至少间隔200ms"""
    global _last_api_time
    now = time.time()
    elapsed = now - _last_api_time
    if elapsed < 0.2:
        time.sleep(0.2 - elapsed)
    _last_api_time = time.time()


def _handle_api_error(e, context: str):
    """
    处理API错误，遇到时间戳错误时自动修复
    返回 True=已处理重试完成, False=未处理返回None
    """
    if not _is_timestamp_error(e):
        print(f"{context}: {e}")
        return None

    print(f"[API] {context} 失败: 时间戳错误，自动恢复中...")
    _sync_system_time()
    time.sleep(1)
    _recover_client()
    # 返回 True 表示调用方需要重试
    return True


def check_balance() -> float:
    try:
        _rate_limit()
        resp = client.rest_api.futures_account_balance_v3()
        for b in resp.data():
            if b.asset == "USDT":
                available = float(b.available_balance or 0)
                print(f"当前账户可用 USDT 余额: {available:<15.8f}")
                return available
        return 0.0
    except Exception as e:
        if _handle_api_error(e, "获取余额") is True:
            return check_balance()
        return 0.0


def check_all_balances():
    try:
        _rate_limit()
        resp = client.rest_api.futures_account_balance_v3()
        balances = resp.data()
        print(f"\n{'='*60}")
        print("  U本位合约账户余额")
        print(f"{'='*60}")
        print(f"{'币种':<10} {'余额':<20} {'未实现盈亏':<15} {'可用':<15}")
        print("-" * 60)
        for b in balances:
            balance = float(b.balance or 0)
            cross_un_pnl = float(b.cross_un_pnl or 0)
            available = float(b.available_balance or 0)
            if balance > 0 or cross_un_pnl != 0:
                print(f"{b.asset:<10} {balance:<20.8f} {cross_un_pnl:<15.8f} {available:<15.8f}")
        print("=" * 60)
    except Exception as e:
        if _handle_api_error(e, "获取余额") is True:
            return check_all_balances()


def set_leverage(symbol: str, leverage: int):
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


def get_current_price(symbol: str = "BTCUSDT") -> float | None:
    _now = time.time()
    _key = f"price_{symbol}"
    if _key in _cache and _now - _cache[_key]["t"] < 5:
        return _cache[_key]["v"]
    try:
        resp = client.rest_api.symbol_price_ticker(symbol=symbol)
        data = resp.data().actual_instance
        rv = float(data.price)
        _cache[_key] = {"t": _now, "v": rv}
        return rv
    except Exception as e:
        if _handle_api_error(e, "获取价格") is True:
            return get_current_price(symbol)
        return None


def get_fills_agg(symbol: str, order_id: int, max_retries: int = 3) -> dict:
    """
    从交易所查询某笔订单的真实成交数据（累加所有成交明细）。

    Returns:
        {
            "qty": float,          # 实际成交数量
            "avg_price": float,    # 加权平均成交价
            "commission": float,   # 手续费 (USDT)
            "realized_pnl": float  # 已实现盈亏
        }
    """
    for attempt in range(max_retries):
        try:
            _rate_limit()
            resp = client.rest_api.account_trade_list(symbol=symbol, order_id=order_id)
            fills = resp.data()
            if not fills:
                if attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                return {"qty": 0.0, "avg_price": 0.0, "commission": 0.0, "realized_pnl": 0.0}

            total_qty = 0.0
            total_quote = 0.0
            total_pnl = 0.0
            total_fee = 0.0

            for fill in fills:
                qty = float(fill.qty or 0)
                price = float(fill.price or 0)
                pnl = float(fill.realized_pnl or 0)
                fee_amt = float(fill.commission or 0)
                fee_asset = fill.commission_asset or ""

                total_qty += qty
                total_quote += qty * price
                total_pnl += pnl

                # 手续费统一折合 USDT
                if fee_asset == "USDT":
                    total_fee += fee_amt
                elif fee_asset not in ("BNB", ""):
                    try:
                        conv_price = get_current_price(f"{fee_asset}USDT")
                        total_fee += fee_amt * conv_price if conv_price else fee_amt
                    except Exception:
                        total_fee += fee_amt
                # BNB折扣或空 → 跳过

            return {
                "qty": round(total_qty, 0),
                "avg_price": round(total_quote / total_qty, 8) if total_qty > 0 else 0.0,
                "commission": round(total_fee, 4),
                "realized_pnl": round(total_pnl, 2),
            }
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            return {"qty": 0.0, "avg_price": 0.0, "commission": 0.0, "realized_pnl": 0.0}
    return {"qty": 0.0, "avg_price": 0.0, "commission": 0.0, "realized_pnl": 0.0}


def place_market_order(symbol: str, side: str, quantity: float):
    try:
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
        else:
            print("  ⚠ 暂未查到成交明细，使用订单返回的估算数据")

        return data, fills
    except Exception as e:
        if _handle_api_error(e, "合约下单") is True:
            return place_market_order(symbol, side, quantity)
        error_msg = str(e)
        print(f"合约下单失败: {error_msg}")
        # 调 AI 分析失败原因
        try:
            from ai.analyzer import analyze_order_error
            analyze_order_error(symbol, side, quantity, error_msg)
        except Exception:
            pass
        empty = {"qty": 0.0, "avg_price": 0.0, "commission": 0.0, "realized_pnl": 0.0}
        return None, empty


def place_stop_loss_order(symbol: str, side: str, quantity: float, entry_price: float, stop_loss_ratio: float = 0.15):
    """
    设置服务器端止损单（STOP_MARKET）
    
    即使程序崩溃/断网，币安服务器也会自动执行止损。
     multi:
      - long:  side=SELL, stopPrice=entry*(1-stop_loss_ratio)
      - short: side=BUY,  stopPrice=entry*(1+stop_loss_ratio)
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
            # 测试网可能不支持 STOP_MARKET，忽略
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
    empty = {"qty": 0.0, "avg_price": 0.0, "commission": 0.0, "realized_pnl": 0.0}
    try:
        pos = get_position(symbol)
        if not pos:
            print("当前无持仓，无需平仓。")
            return None, empty
        qty = abs(float(pos["position_amt"]))
        side = "SELL" if float(pos["position_amt"]) > 0 else "BUY"
        direction = "多" if side == "SELL" else "空"

        # 检查交易所单笔限额，超限时拆单
        from strategy.auto_trader import get_symbol_limits
        limits = get_symbol_limits(symbol)
        max_qty = int(limits.get("max_qty", 10_000_000_000))
        close_qty = int(min(qty, max_qty))

        if close_qty < qty:
            print(f"平仓: {symbol} {direction} {qty} -> 单笔限额{max_qty}，分批平仓({close_qty})")
        else:
            print(f"平仓: {symbol} {direction} {qty}")

        return place_market_order(symbol=symbol, side=side, quantity=close_qty)
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


def get_position(symbol: str = "BTCUSDT"):
    _now = time.time()
    _key = f"pos_{symbol}"
    if _key in _cache and _now - _cache[_key]["t"] < 5:
        return _cache[_key]["v"]
    try:
        _rate_limit()
        resp = client.rest_api.position_information_v3(symbol=symbol)
        for p in resp.data():
            if float(p.position_amt) != 0:
                rv = {
                    "symbol": p.symbol,
                    "position_amt": p.position_amt,
                    "entry_price": p.entry_price,
                    "mark_price": getattr(p, "mark_price", 0),
                    "un_realized_profit": p.un_realized_profit,
                }
                _cache[_key] = {"t": _now, "v": rv}
                return rv
        _cache[_key] = {"t": _now, "v": None}
        return None
    except Exception as e:
        if _handle_api_error(e, "获取持仓") is True:
            return get_position(symbol)
        print(f"获取持仓失败: {e}")
        return None


def has_open_position() -> bool:
    """
    查询交易所是否有任何币种持仓。

    每次启动时用于校验本地风险状态是否与交易所同步。
    返回 True 表示交易所至少有一个仓位（做多或做空）。
    """
    try:
        _rate_limit()
        resp = client.rest_api.position_information_v3()
        for p in resp.data():
            if abs(float(p.position_amt)) > 0:
                return True
        return False
    except Exception as e:
        print(f"[全仓查询] 失败: {e}")
        return False


def get_open_position_symbol() -> str | None:
    """
    查询交易所第一个有持仓的币种符号。
    用于启动时恢复风险状态。
    """
    try:
        _rate_limit()
        resp = client.rest_api.position_information_v3()
        for p in resp.data():
            if abs(float(p.position_amt)) > 0:
                return p.symbol
        return None
    except Exception as e:
        print(f"[查询持仓币种] 失败: {e}")
        return None
