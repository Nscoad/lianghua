"""
币安 API 查询层 — 余额、价格、持仓、币种限制
"""
import time
from core.client import client, _rate_limit, _handle_api_error, _cache


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
    """查询交易所是否有任何币种持仓"""
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
    """查询交易所第一个有持仓的币种符号"""
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


def _get_symbol_limits(symbol: str) -> dict:
    """获取币种交易限制参数（min_qty, max_qty, step_size 等）"""
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
