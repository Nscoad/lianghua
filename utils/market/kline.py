"""
实时K线分析 — 从币安U本位合约API获取15m K线，用于趋势判断和入场分析
"""
import time

import requests as _requests

from config import get_futures_config


# ==================== 实时K线统一获取接口（30秒缓存 + 限频） ====================

_KLINES_CACHE: dict[str, tuple[float, list]] = {}
_KLINES_CACHE_TTL = 30

_FUTURES_BASE = get_futures_config()["base_url"]  # 跟随 config.py 的 USE_TESTNET 切换
_FUTURES_API_KEY = get_futures_config()["api_key"]  # 带key请求，额度更高
_LAST_KLINE_REQUEST = 0.0
_KLINE_MIN_INTERVAL = 0.5  # 相邻K线请求至少间隔500ms


def _fetch_real_klines(symbol: str, limit: int = 6, interval: str = "15m") -> list[dict]:
    """
    从币安U本位合约API获取实时K线（失败自动重试2次）。
    返回 [{open, high, low, close, vol, time}, ...]
    """
    global _KLINES_CACHE, _LAST_KLINE_REQUEST
    cache_key = f"{symbol}_{limit}_{interval}"

    # 缓存检查
    now = time.time()
    if cache_key in _KLINES_CACHE:
        cached_time, cached_data = _KLINES_CACHE[cache_key]
        if now - cached_time < _KLINES_CACHE_TTL:
            return cached_data

    url = f"{_FUTURES_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    headers = {
        "X-MBX-APIKEY": _FUTURES_API_KEY,
        "User-Agent": "Mozilla/5.0",
    }

    # 限频：相邻K线请求至少间隔500ms
    elapsed = time.time() - _LAST_KLINE_REQUEST
    if elapsed < _KLINE_MIN_INTERVAL:
        time.sleep(_KLINE_MIN_INTERVAL - elapsed)

    # 失败后重试最多2次（共3次尝试）
    for attempt in range(3):
        try:
            resp = _requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            _LAST_KLINE_REQUEST = time.time()
            data = resp.json()
            result = []
            for k in data:
                result.append({
                    "time": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "vol": float(k[5]),
                })
            _KLINES_CACHE[cache_key] = (now, result)
            return result
        except Exception as e:
            # 清除缓存，确保下次调用重新尝试
            if cache_key in _KLINES_CACHE:
                del _KLINES_CACHE[cache_key]
            if attempt < 2:
                wait = 2 * (attempt + 1)
                print(f"[K线] {symbol} 获取失败(重试{attempt+1}/2): {e}，{wait}秒后重试")
                time.sleep(wait)
            else:
                print(f"[K线] {symbol} 获取失败(已重试3次): {e}")
    return []


# ==================== K线分析函数 ====================


def get_kline_levels(symbol: str, lookback: int = 6, interval: str = "15m") -> dict | None:
    """
    分析最近 lookback 根K线的关键水位。

    Returns:
        {"current_price", "prev_high", "prev_low", "trend", "volume"}
        trend: "up" | "down" | "sideways"
    """
    kl = _fetch_real_klines(symbol, limit=lookback, interval=interval)
    if len(kl) < 4:
        return None

    prices = [k["close"] for k in kl]
    highs = [k["high"] for k in kl]
    lows = [k["low"] for k in kl]
    vols = [k["vol"] for k in kl]

    current = prices[-1]
    prev_high = max(highs)
    prev_low = min(lows)
    avg_vol = sum(vols) / len(vols)

    # 趋势判断：使用简单移动平均 + K线方向比例
    ma_short = sum(prices[-3:]) / 3 if len(prices) >= 3 else current
    ma_long = sum(prices) / len(prices)

    # 统计K线方向：至少 2/3（即 6根中>=4根）同向才算有效趋势
    bullish_count = sum(1 for k in kl if k["close"] >= k["open"])
    bearish_count = len(kl) - bullish_count

    # up: 当前在MA3之上，MA3 > MA均线，且多数K线为阳线
    # down: 当前在MA3之下，MA3 < MA均线，且多数K线为阴线
    # sideways: 其他
    min_dir_count = max(2, int(len(kl) * 2 / 3))  # 至少 2/3
    if current > ma_short * 1.005 and ma_short > ma_long * 1.005 and bullish_count >= min_dir_count:
        trend = "up"
    elif current < ma_short * 0.995 and ma_short < ma_long * 0.995 and bearish_count >= min_dir_count:
        trend = "down"
    else:
        trend = "sideways"

    return {
        "current_price": current,
        "prev_high": prev_high,
        "prev_low": prev_low,
        "trend": trend,
        "volume": avg_vol,
        "ma_short": ma_short,
        "ma_long": ma_long,
    }


def check_kline_entry(symbol: str, want_long: bool, interval: str = "15m") -> dict | None:
    """
    判断当前是否适合入场。
    want_long=True: 做多检查
    want_long=False: 做空检查

    Returns:
        {"trend": "up"|"down"|"sideways",
         "can_enter": bool,
         "reason": str,
         "entry_mode": "trend"|"volatility_override"|"sideways"}
    """
    levels = get_kline_levels(symbol, lookback=6, interval=interval)
    if not levels:
        return {"trend": "unknown", "can_enter": True, "reason": "数据不足，默认放行",
                "entry_mode": "trend"}

    trend = levels["trend"]

    # 检查最新5分K线振幅是否超过9.3%（强波动信号，可覆盖趋势判断）
    # 使用 requests 直接调用（不走缓存/重试），避免 418 污染主K线日志
    m5_range = 0
    try:
        import requests as _req
        _b = get_futures_config()["base_url"]
        _k = get_futures_config()["api_key"]
        _r = _req.get(
            f"{_b}/fapi/v1/klines?symbol={symbol}&interval=5m&limit=1",
            headers={"X-MBX-APIKEY": _k, "User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if _r.status_code == 200:
            _d = _r.json()
            if _d:
                _c = _d[0]
                m5_range = (float(_c[2]) - float(_c[3])) / float(_c[3])
    except Exception:
        pass

    current = levels["current_price"]
    ma_short = levels.get("ma_short", current)
    ma_long = levels.get("ma_long", current)

    is_override = m5_range > 0.093

    def _make_reason(t: str, can: bool) -> str:
        extra = f" | 5分振幅{m5_range*100:.1f}%>9.3%，强波动覆盖" if is_override else ""
        if t in ("up", "down"):
            return f"{'上升趋势 up' if t == 'up' else '下降趋势 down'} (MA3={ma_short:.8f}, MA6={ma_long:.8f}){extra}"
        return f"横盘震荡 (MA3={ma_short:.8f}, MA6={ma_long:.8f}){extra}"

    def _result(t: str, can: bool, override: bool = False) -> dict:
        return {
            "trend": t, "can_enter": can,
            "reason": _make_reason(t, can),
            "entry_mode": "volatility_override" if override else ("trend" if t in ("up", "down") else "sideways"),
        }

    if want_long:
        if trend == "up":
            return _result("up", True)
        elif trend == "down":
            if is_override:
                return _result("down", True, override=True)
            return _result("down", False)
        else:
            return _result("sideways", False)
    else:
        if trend == "down":
            return _result("down", True)
        elif trend == "up":
            if is_override:
                return _result("up", True, override=True)
            return _result("up", False)
        else:
            return _result("sideways", False)
