"""
Streaming 流式回测引擎 — 逐 K 线回放，实时生成信号，杜绝未来函数
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

from datetime import datetime, timedelta
from collections import deque

LEVERAGE = 5
MARGIN_RATIO = 0.2
STOP_LOSS = -0.40
TAKE_PROFIT = 0.40
TP_REDUCE = 0.55


def _calc_ema(values: list, period: int) -> list:
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append((v - ema[-1]) * multiplier + ema[-1])
    return ema


def _calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50
    gains = losses = 0.0
    for i in range(-period, 0):
        chg = closes[i] - closes[i - 1]
        if chg > 0: gains += chg
        else: losses -= chg
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_macd(closes: list) -> tuple:
    ema12 = _calc_ema(closes, 12)
    ema26 = _calc_ema(closes, 26)
    if not ema12 or not ema26:
        return 0, 0, False
    macd = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal = _calc_ema(macd, 9)
    if not signal or len(macd) < 2 or len(signal) < 2:
        return macd[-1] if macd else 0, signal[-1] if signal else 0, False
    cross = macd[-1] > signal[-1] and macd[-2] <= signal[-2]
    return macd[-1], signal[-1], cross


def run_streaming_backtest(symbol: str, interval: str, days: int,
                           initial_margin: float = 100, leverage: int = 5) -> list:
    """逐K线流式回测"""
    # 直接调用实时API获取K线
    from utils.historical_data import _fetch_real_klines
    data = _fetch_real_klines(symbol, limit=days * 24)
    if not data or len(data) < 20:
        print(f"[回测] {symbol} 实时K线不足")
        return []

    # 不依赖 SQLite，直接用实时数据
    # 构建行数据接口（兼容原有格式：open, high, low, close, volume）
    class FakeRow:
        def __init__(self, k):
            self.open_time = int(k[0])
            self.open = float(k[1])
            self.high = float(k[2])
            self.low = float(k[3])
            self.close = float(k[4])
            self.volume = float(k[5])
    rows = [FakeRow(k) for k in data]

    if not rows:
        print(f"[回测] 无K线数据: {symbol}")
        return []

    print(f"[回测] 加载 {len(rows)} 根K线\n")

    # Streaming 状态
    closes = deque(maxlen=100)
    highs = deque(maxlen=100)
    lows = deque(maxlen=100)
    volumes = deque(maxlen=100)
    timestamps = []

    position = 0          # >0 多, <0 空
    entry_price = 0.0
    margin = initial_margin
    trades = []

    for row in rows:
        ts, open_p, high_p, low_p, close_p, vol = row[0], row[1], row[2], row[3], row[4], row[5]
        opens = float(open_p)
        high = float(high_p)
        low = float(low_p)
        close = float(close_p)
        volume = float(vol) if vol else 0

        closes.append(close)
        highs.append(high)
        lows.append(low)
        volumes.append(volume)
        timestamps.append(ts)

        ts_dt = datetime.fromtimestamp(ts / 1000)

        if len(closes) < 20:
            continue

        # ===== 实时计算指标 =====
        ma5 = sum(list(closes)[-5:]) / 5
        ma20 = sum(list(closes)[-20:]) / 20
        rsi = _calc_rsi(list(closes))
        macd_line, signal_line, macd_cross = _calc_macd(list(closes))
        avg_vol = sum(list(volumes)[-10:]) / 10 if len(volumes) >= 10 else volume
        vol_surge = volume > avg_vol * 1.2

        trend_up = ma5 > ma20
        price_above_ma5 = close > ma5

        # ===== 信号生成（模拟AI逻辑） =====
        signal = None
        confidence = 0

        # 做多条件
        buy_cond = trend_up and price_above_ma5 and rsi > 35 and rsi < 70
        sell_cond = not trend_up and not price_above_ma5 and rsi < 65 and rsi > 30

        if buy_cond:
            signal = "buy"
            confidence = min(85, 60 + int(rsi // 5) + (10 if macd_cross else 0) + (5 if vol_surge else 0))
        elif sell_cond:
            signal = "sell"
            confidence = min(85, 60 + int((100 - rsi) // 5) + (10 if macd_cross else 0) + (5 if vol_surge else 0))

        # ===== 持仓风控 =====
        if position != 0:
            unrealized = (close - entry_price) * abs(position) if position > 0 else (entry_price - close) * abs(position)
            pos_margin = abs(position) * entry_price / leverage
            pnl_ratio = unrealized / pos_margin if pos_margin > 0 else 0

            # 止损
            if pnl_ratio <= STOP_LOSS:
                pnl = (close - entry_price) * position
                trades.append({
                    "time": ts_dt, "side": "LONG" if position > 0 else "SHORT",
                    "reason": "stop_loss", "entry": entry_price, "exit": close,
                    "pnl": round(pnl, 2), "margin": margin,
                })
                margin += pnl
                position = 0
                entry_price = 0.0
                continue

            # 止盈 TP1
            if pnl_ratio >= TAKE_PROFIT and not hasattr(run_streaming_backtest, '_tp_done'):
                reduce_qty = abs(int(position * TP_REDUCE))
                if reduce_qty > 0 and reduce_qty < abs(position):
                    pnl_part = (close - entry_price) * reduce_qty if position > 0 else (entry_price - close) * reduce_qty
                    trades.append({
                        "time": ts_dt, "side": "LONG" if position > 0 else "SHORT",
                        "reason": "take_profit", "entry": entry_price, "exit": close,
                        "pnl": round(pnl_part, 2), "margin": margin, "partial": True,
                    })
                    margin += pnl_part
                    if position > 0:
                        position -= reduce_qty
                    else:
                        position += reduce_qty
                    run_streaming_backtest._tp_done = True

        # ===== 开仓 =====
        if position == 0 and signal in ("buy", "sell") and confidence >= 65:
            want_long = signal == "buy"
            qty = int(margin * MARGIN_RATIO * leverage / close)
            if qty >= 1:
                position = qty if want_long else -qty
                entry_price = close
                if hasattr(run_streaming_backtest, '_tp_done'):
                    del run_streaming_backtest._tp_done

    # 收尾：平掉尾仓
    if position != 0:
        pnl = (close - entry_price) * position
        trades.append({
            "time": datetime.fromtimestamp(rows[-1][0] / 1000),
            "side": "LONG" if position > 0 else "SHORT",
            "reason": "close", "entry": entry_price, "exit": close,
            "pnl": round(pnl, 2), "margin": margin,
        })
        margin += pnl
        position = 0

    return trades
