from collector.feeds_db import load_signals
from utils.db import get_trade_records
from datetime import datetime, timedelta

signals = load_signals()
cutoff = datetime.now() - timedelta(hours=6)
print(f"=== 近6小时交易信号 ({sum(1 for s in signals if s['timestamp'] >= cutoff.isoformat()[:19])}条) ===")
for s in signals[-30:]:
    ts = s['timestamp']
    sym = s.get('symbol', '?')
    act = s['action']
    conf = s.get('confidence', 0)
    reason = s.get('reason', '')[:80]
    print(f"  {ts[:19]} | {sym:<12} | {act:<5} | 信心:{conf}% | {reason}")

print()
print("=== 近1小时开平仓流水 ===")
records = get_trade_records(200)
cutoff1h = datetime.now() - timedelta(hours=1)
for r in records:
    t = r['time'] if isinstance(r['time'], str) else r['time']
    if len(t) > 19: t = t[:19]
    if t >= (datetime.now() - timedelta(hours=1)).isoformat()[:19]:
        pnl = r.get('net_pnl', r['realized_pnl'])
        print(f"  {t} | {r['symbol']:<12} | {r['side']:<5} | {r['reason']:<15} | pnl={pnl:+.2f}")
