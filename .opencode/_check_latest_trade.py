"""查看最新亏损交易 + K线数据"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.db import _get_trade_conn
from utils.market.kline import get_kline_levels, _fetch_real_klines
import json

conn = _get_trade_conn()

# 最新的亏损交易（fast_sl 或 stop_loss）
rows = conn.execute(
    "SELECT * FROM trade_records WHERE reason = 'fast_sl' ORDER BY id DESC LIMIT 3"
).fetchall()

if not rows:
    print("没有快捞止损记录")
else:
    for r in rows:
        d = dict(r)
        print(f"=== 亏损交易 ===")
        print(json.dumps({k: str(v) for k, v in d.items()}, ensure_ascii=False, indent=2))
        sym = d["symbol"]
        print(f"\n--- {sym} 当前6根15m K线 ---")
        kl = _fetch_real_klines(sym, limit=6, interval="15m")
        if kl:
            for k in kl:
                t = k["time"]
                from datetime import datetime
                ts = datetime.fromtimestamp(t / 1000).strftime("%H:%M")
                direction = "🟢" if k["close"] >= k["open"] else "🔴"
                print(f"  {ts} {direction} 开{k['open']:.6f} 高{k['high']:.6f} 低{k['low']:.6f} 收{k['close']:.6f} 涨幅{(k['close']-k['open'])/k['open']*100:+.2f}%")
        else:
            print(f"  K线数据获取失败")
        
        # 获取趋势判断
        print(f"\n--- {sym} 趋势判断 ---")
        levels = get_kline_levels(sym, lookback=6)
        if levels:
            print(f"  趋势: {levels['trend']}")
            print(f"  current: {levels['current_price']:.6f}")
            print(f"  MA3: {levels['ma_short']:.6f}")
            print(f"  MA6: {levels['ma_long']:.6f}")
            if levels['current_price'] > levels['ma_short'] * 1.005 and levels['ma_short'] > levels['ma_long'] * 1.005:
                print(f"  → up条件: 当前>{levels['ma_short']*1.005:.6f} AND MA3>{levels['ma_long']*1.005:.6f}")
            elif levels['current_price'] < levels['ma_short'] * 0.995 and levels['ma_short'] < levels['ma_long'] * 0.995:
                print(f"  → down条件: 当前<{levels['ma_short']*0.995:.6f} AND MA3<{levels['ma_long']*0.995:.6f}")
            else:
                print(f"  → sideways条件: 其他")
