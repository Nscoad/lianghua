"""
实时K线分析 — 从币安实时API获取1h K线，用于趋势判断和入场分析
"""
import json
import ssl
import time
import urllib.error
import urllib.request


# ==================== 实时K线统一获取接口（30秒缓存） ====================

_KLINES_CACHE: dict[str, tuple[float, list]] = {}
_KLINES_CACHE_TTL = 30


def _fetch_real_klines(symbol: str, limit: int = 6, interval: str = "1h") -> list[dict]:
    """
    从币安现货API获取实时K线。
    返回 [{open, high, low, close, vol, time}, ...]
    """
    global _KLINES_CACHE
    cache_key = f"{symbol}_{limit}_{interval}"

    # 缓存检查
    now = time.time()
    if cache_key in _KLINES_CACHE:
        cached_time, cached_data = _KLINES_CACHE[cache_key]
        if now - cached_time < _KLINES_CACHE_TTL:
            return cached_data

    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urllib.request.urlopen(url, context=ctx, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
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
    except (urllib.error.URLError, Exception) as e:
        print(f"[K线] {symbol} 获取失败: {e}")
        return []


# ==================== K线分析函数 ====================


def get_kline_levels(symbol: str, lookback: int = 6, interval: str = "1h") -> dict | None:
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

    # 趋势判断：使用简单移动平均
    ma_short = sum(prices[-3:]) / 3 if len(prices) >= 3 else current
    ma_long = sum(prices) / len(prices)

    # up: 当前在MA3之上，MA3 > MA均线
    # down: 当前在MA3之下，MA3 < MA均线
    # sideways: 其他
    if current > ma_short * 1.005 and ma_short > ma_long * 1.005:
        trend = "up"
    elif current < ma_short * 0.995 and ma_short < ma_long * 0.995:
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


def check_kline_entry(symbol: str, want_long: bool, interval: str = "1h") -> dict | None:
    """
    判断当前是否适合入场。
    want_long=True: 做多检查
    want_long=False: 做空检查

    Returns:
        {"trend": "up"|"down"|"sideways",
         "can_enter": bool,
         "reason": str}
    """
    levels = get_kline_levels(symbol, lookback=6, interval=interval)
    if not levels:
        return {"trend": "unknown", "can_enter": True, "reason": "数据不足，默认放行"}

    trend = levels["trend"]
    current = levels["current_price"]
    ma_short = levels.get("ma_short", current)
    ma_long = levels.get("ma_long", current)

    if want_long:
        if trend == "up":
            return {"trend": "up", "can_enter": True, "reason": f"上升趋势 up (MA3={ma_short:.8f}, MA6={ma_long:.8f})"}
        elif trend == "down":
            return {"trend": "down", "can_enter": False, "reason": f"下跌趋势中，不做多 (MA3={ma_short:.8f}, MA6={ma_long:.8f})"}
        else:
            return {"trend": "sideways", "can_enter": True, "reason": f"横盘震荡，可做 (MA3={ma_short:.8f}, MA6={ma_long:.8f})"}
    else:
        if trend == "down":
            return {"trend": "down", "can_enter": True, "reason": f"下降趋势 down (MA3={ma_short:.8f}, MA6={ma_long:.8f})"}
        elif trend == "up":
            return {"trend": "up", "can_enter": False, "reason": f"上升趋势中，不做空 (MA3={ma_short:.8f}, MA6={ma_long:.8f})"}
        else:
            return {"trend": "sideways", "can_enter": True, "reason": f"横盘震荡，可做 (MA3={ma_short:.8f}, MA6={ma_long:.8f})"}
