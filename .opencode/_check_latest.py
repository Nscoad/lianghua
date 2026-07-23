"""查看最新交易和当前仓位"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.db import _get_trade_conn

conn = _get_trade_conn()

# 最近20笔
rows = conn.execute("SELECT * FROM trade_records ORDER BY id DESC LIMIT 20").fetchall()
print("=== 最近20笔交易 ===")
for r in reversed(rows):
    d = dict(r)
    print(f'{str(d["time"])[:19]} {d["symbol"]:<18} {d["side"]:<6} {d["reason"]:<16} '
          f'qty={d["qty"]:<8} entry={d["entry_price"]} exit={d["exit_price"]} '
          f'pnl={d["net_pnl"]:+.2f}')

print()

# 看大额亏损
print("=== 亏损>50U的交易 ===")
rows2 = conn.execute(
    "SELECT * FROM trade_records WHERE reason != 'open' AND net_pnl < -50 ORDER BY id DESC"
).fetchall()
for r in rows2:
    d = dict(r)
    margin_est = abs(d["qty"] * d["entry_price"] / 5) if d["entry_price"] else 0
    print(f'{str(d["time"])[:19]} {d["symbol"]:<18} {d["side"]:<6} {d["reason"]:<16} '
          f'pnl={d["net_pnl"]:+.2f} | 估算保证金~{margin_est:.0f} | '
          f'亏损率={d["net_pnl"]/max(margin_est,1)*100:.1f}%')
