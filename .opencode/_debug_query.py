from utils.trade_records import get_trade_records, calc_period_stats
from datetime import datetime, timedelta
import json

cutoff = datetime.now() - timedelta(hours=3)
records = [r for r in get_trade_records(999) if datetime.fromisoformat(r['time']) >= cutoff and r['reason'] != 'open']

print("=== ACEUSDT ===")
ace = [r for r in records if r['symbol'] == 'ACEUSDT']
for r in ace:
    pnl = r.get('net_pnl', r['realized_pnl'])
    print(f"  {r['time'][11:19]} | {r['side']:<5} | {r['reason']:<15} | pnl={pnl:+.2f} | partial={r.get('is_partial',False)} | qty={r.get('qty','')}")

print("\n=== PROMUSDT ===")
prom = [r for r in records if r['symbol'] == 'PROMUSDT']
for r in prom:
    pnl = r.get('net_pnl', r['realized_pnl'])
    print(f"  {r['time'][11:19]} | {r['side']:<5} | {r['reason']:<15} | pnl={pnl:+.2f} | partial={r.get('is_partial',False)} | qty={r.get('qty','')}")

print("\n=== BANKUSDT ===")
bank = [r for r in records if r['symbol'] == 'BANKUSDT']
for r in bank:
    pnl = r.get('net_pnl', r['realized_pnl'])
    print(f"  {r['time'][11:19]} | {r['side']:<5} | {r['reason']:<15} | pnl={pnl:+.2f} | partial={r.get('is_partial',False)} | qty={r.get('qty','')}")

# 读取分析汇总
print("\n=== AI复盘分析 ===")
import os
af = os.path.join('data', 'analysis_summary.jsonl')
if os.path.exists(af):
    with open(af, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                t = datetime.fromisoformat(r['time'])
                if t >= datetime.now() - timedelta(hours=3):
                    print(f"  {r['time'][11:19]} | {r['period']}")
                    print(f"    原因: {r['analysis'].get('root_cause','')}")
                    print(f"    建议: {r['analysis'].get('suggestions','')}")
