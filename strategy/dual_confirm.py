"""
双确认信号检查 — 冷却状态下的开仓过滤条件

条件（三选二达标）：
  A. 价格站上 MA5 且 15分钟收盘突破前高（做多）/ 跌破前低（做空）
  B. RSI(14)回升至35+ 且 MACD金叉（做多）/ RSI<65 且 MACD死叉（做空）
  C. 成交量 > 近10根均量
"""
import requests as _req
from config import get_futures_config


def _fetch_15m_klines(symbol: str, limit: int = 50) -> list:
    cfg = get_futures_config()
    try:
        resp = _req.get(
            f"{cfg['base_url']}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "15m", "limit": limit},
            headers={"X-MBX-APIKEY": cfg["api_key"]},
            timeout=10,
        )
        return resp.json() if resp.status_code == 200 else []
    except Exception:
        return []


def _calc_ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append((v - ema[-1]) * multiplier + ema[-1])
    return ema


def check_dual_confirmation(symbol: str, want_long: bool) -> dict:
    klines = _fetch_15m_klines(symbol, limit=50)
    if len(klines) < 20:
        return {"passed": False, "reason": "K线数据不足", "details": {}}

    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    current_close = closes[-1]
    flags = {"A": False, "B": False, "C": False}
    reasons = []

    # ---- 条件A ----
    ma5 = sum(closes[-5:]) / 5
    break_high = current_close > highs[-2]
    above_ma5 = current_close > ma5
    cond_a = (above_ma5 and break_high) if want_long else (current_close < ma5 and current_close < lows[-2])
    if cond_a:
        flags["A"] = True
        reasons.append(f"A OK MA5={ma5:.6f}")
    else:
        reasons.append(f"A NO MA5={ma5:.6f} above={above_ma5} break={break_high}")

    # ---- 条件B ----
    if len(closes) >= 15:
        gains = losses = 0.0
        for i in range(-14, 0):
            chg = closes[i] - closes[i - 1]
            if chg > 0: gains += chg
            else: losses -= chg
        rs = (gains / 14) / (losses / 14) if losses > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        cond_b_rsi = rsi > 35 if want_long else rsi < 65

        macd_line_data = [c - e for c, e in zip(_calc_ema(closes, 12) or [], _calc_ema(closes, 26) or [])]
        signal_line = _calc_ema(macd_line_data, 9) if len(macd_line_data) >= 9 else []
        cond_b_macd = False
        if signal_line and len(macd_line_data) >= 2 and len(signal_line) >= 2:
            cond_b_macd = macd_line_data[-1] > signal_line[-1] and macd_line_data[-2] <= signal_line[-2]

        cond_b = cond_b_rsi and cond_b_macd
        if cond_b:
            flags["B"] = True
            reasons.append(f"B OK RSI={rsi:.1f} MACD金叉")
        else:
            reasons.append(f"B NO RSI={rsi:.1f} MACD={cond_b_macd}")
    else:
        reasons.append("B NO RSI数据不足")

    # ---- 条件C ----
    avg_vol_10 = sum(volumes[-10:]) / 10
    cond_c = volumes[-1] > avg_vol_10
    if cond_c:
        flags["C"] = True
        reasons.append(f"C OK vol={volumes[-1]:.0f} > avg={avg_vol_10:.0f}")
    else:
        reasons.append(f"C NO vol={volumes[-1]:.0f} <= avg={avg_vol_10:.0f}")

    cond_pair = (flags["A"] and flags["B"]) or (flags["A"] and flags["C"])
    return {
        "passed": cond_pair,
        "reason": " | ".join(reasons),
        "details": flags,
    }
