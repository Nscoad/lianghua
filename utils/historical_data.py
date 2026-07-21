"""
实时K线分析 — 从币安实时API获取1h K线，用于趋势判断和入场分析
"""
import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Optional


# ==================== 实时K线统一获取接口（30秒缓存） ====================

_KLINES_CACHE: dict[str, tuple[float, list]] = {}
_KLINES_CACHE_TTL = 30


def _fetch_real_klines(symbol: str, limit: int = 24) -> Optional[list]:
    """从币安实时API获取1h K线，带缓存（SSL超时自动重试1次）"""
    cache_key = f"{symbol}_{limit}"
    now = time.time()
    cached = _KLINES_CACHE.get(cache_key)
    if cached and now - cached[0] < _KLINES_CACHE_TTL:
        return cached[1]

    def _do_fetch():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit={limit}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        return json.loads(resp.read().decode("utf-8"))

    for attempt in range(2):
        try:
            data = _do_fetch()
            if data and len(data) >= 4:
                _KLINES_CACHE[cache_key] = (now, data)
                return data
        except Exception as e:
            if attempt == 0 and isinstance(e, (ssl.SSLError, TimeoutError, urllib.error.URLError)):
                _KLINES_CACHE.clear()
                time.sleep(3)
                continue
            print(f"[K线实时] {symbol} 获取失败: {e}")
            return None
    return None


# ==================== K线入场分析 ====================

def check_kline_entry(symbol: str, want_long: bool) -> dict:
    """
    分析K线判断入场时机（实时API）。

    从币安实时API获取最近6根1h K线，分析：
    - MA3 vs MA6 判断短期趋势方向
    - 近4根高低点范围 vs 6根范围 → 突破判断
    - 近3根均量 vs 6根均量 → 量能配合

    Returns:
        {"decision": "enter"|"wait"|"skip",
         "reason": "原因说明",
         "trend": "up"|"down"|"sideways"}
    """
    data = _fetch_real_klines(symbol, limit=6)
    if not data or len(data) < 4:
        return {"decision": "enter", "reason": "K线实时数据不足（<4根），默认入场",
                "trend": "sideways"}

    closes = [float(k[4]) for k in data]
    highs = [float(k[2]) for k in data]
    lows = [float(k[3]) for k in data]
    volumes = [float(k[5]) for k in data]
    n = len(data)

    # MA3 vs MA6（短均线 vs 略长均线）
    ma3 = sum(closes[-3:]) / 3
    ma6 = sum(closes[-6:]) / min(6, n)
    current = closes[-1]

    # 方向判断
    if want_long:
        if current > ma3 > ma6 * 1.005:
            trend = "up"
        elif current < ma6 * 0.995:
            trend = "down"
        else:
            trend = "sideways"
    else:
        if current < ma3 < ma6 * 0.995:
            trend = "down"
        elif current > ma6 * 1.005:
            trend = "up"
        else:
            trend = "sideways"

    # 近4根K线的范围 vs 全部范围
    recent_high = max(highs[-4:])
    recent_low = min(lows[-4:])
    all_high = max(highs)
    all_low = min(lows)
    range_ratio = (recent_high - recent_low) / (all_high - all_low) if (all_high - all_low) > 0 else 1

    # 近3根均量 vs 全部均量
    avg_vol_recent = sum(volumes[-3:]) / 3
    avg_vol_all = sum(volumes) / n
    vol_ratio = avg_vol_recent / avg_vol_all if avg_vol_all > 0 else 1

    # 涨跌幅（最后1根 vs 前一根）
    last_change = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 and closes[-2] > 0 else 0

    # 决策
    reasons = []

    if range_ratio > 0.6 and vol_ratio > 1.2 and abs(last_change) > 0.3:
        reasons.append(f"放量突破(范围比{range_ratio:.0%} 量比{vol_ratio:.1f})")
        decision = "enter"
    elif range_ratio < 0.3 and vol_ratio < 0.8:
        reasons.append(f"横盘(范围比{range_ratio:.0%} 量比{vol_ratio:.1f})")
        decision = "wait"
    elif trend == "sideways":
        reasons.append(f"横盘趋势(MA3={ma3:.6f} MA6={ma6:.6f})")
        decision = "wait"
    elif (want_long and trend == "up") or (not want_long and trend == "down"):
        reasons.append(f"趋势{trend}(MA3={ma3:.6f} MA6={ma6:.6f})")
        decision = "enter"
    else:
        reasons.append(f"逆势{trend}, 等待")
        decision = "wait"

    reason_str = "; ".join(reasons)
    return {"decision": decision, "reason": reason_str, "trend": trend}


def check_kline_entry_main(symbol: str, want_long: bool, candidates: list[str] = None) -> dict:
    """
    主入口：先检查主币种K线，如果横盘则尝试候选币种。
    全部横盘则返回 wait。
    """
    import time as _time

    # 第一轮：主币种
    result = check_kline_entry(symbol, want_long)
    print(f"  [K线] {symbol} {result['trend']} → {result['decision']} ({result['reason']})")

    if result["decision"] == "enter":
        return dict(result, symbol=symbol)

    if result["decision"] == "wait":
        print(f"  [K线] {symbol} 横盘中，等180秒后重查...")
        _time.sleep(180)

        result = check_kline_entry(symbol, want_long)
        print(f"  [K线] 重查 {symbol} {result['trend']} → {result['decision']} ({result['reason']})")

        if result["decision"] == "enter":
            return dict(result, symbol=symbol)

        # 还是横盘 → 尝试候选币种
        if candidates:
            print(f"  [K线] {symbol} 仍横盘，尝试候选币种: {candidates}")
            for c in candidates:
                if c == symbol:
                    continue
                c_result = check_kline_entry(c, want_long)
                print(f"  [K线] 候选 {c} {c_result['trend']} → {c_result['decision']} ({c_result['reason']})")
                if c_result["decision"] == "enter":
                    return dict(c_result, symbol=c)

    return dict(result, symbol=symbol)


# ==================== K线关键位分析（供风控使用） ====================

def get_kline_levels(symbol: str, lookback: int = 24) -> Optional[dict]:
    """
    从币安实时1h K线获取前高前低和盘整判断（供 risk_monitor 风控使用）。

    Args:
        symbol: 币种，如 BTCUSDT
        lookback: 回看K线数量（默认24根=1天）

    Returns:
        prev_high: 回看范围内最高价（前高阻力）
        prev_low:  回看范围内最低价（前低支撑）
        current_price: 当前最新价
        trend: up / down / sideways
        is_consolidating: 最近3根K线是否盘整
        consolidation_reason: 盘整原因
        bars_no_direction: 最近3根无明显方向的数量
        high_3: 最近3根最高
        low_3: 最近3根最低
    """
    data = _fetch_real_klines(symbol, limit=lookback)
    if not data or len(data) < 6:
        return None

    highs = [float(k[2]) for k in data]
    lows = [float(k[3]) for k in data]
    closes = [float(k[4]) for k in data]
    current_price = closes[-1]

    prev_high = max(highs)
    prev_low = min(lows)

    # MA3 vs MA6 趋势
    ma3 = sum(closes[-3:]) / 3
    ma6 = sum(closes[-6:]) / 6
    if ma3 > ma6 * 1.005:
        trend = "up"
    elif ma3 < ma6 * 0.995:
        trend = "down"
    else:
        trend = "sideways"

    # 最近3根K线盘整判断
    h3 = max(highs[-3:])
    l3 = min(lows[-3:])
    range_3 = (h3 - l3) / closes[-3] * 100

    all_range = (prev_high - prev_low) / prev_low * 100

    is_consolidating = False
    reasons = []

    if range_3 < all_range * 0.2 and range_3 < 1.0:
        is_consolidating = True
        reasons.append(f"3根振幅{range_3:.2f}%范围过窄")
    if all_range < 2.0:
        is_consolidating = True
        reasons.append(f"24h振幅仅{all_range:.2f}%整体盘整")

    # 最近3根K线是否无明显方向
    bars_no_direction = 0
    for i in range(-3, 0):
        body_range = abs(closes[i] - float(data[i][1]))
        candle_range = highs[i] - lows[i]
        if candle_range > 0 and body_range / candle_range < 0.3:
            bars_no_direction += 1

    return {
        "prev_high": prev_high,
        "prev_low": prev_low,
        "current_price": current_price,
        "trend": trend,
        "is_consolidating": is_consolidating,
        "consolidation_reason": "; ".join(reasons),
        "bars_no_direction": bars_no_direction,
        "high_3": h3,
        "low_3": l3,
    }
