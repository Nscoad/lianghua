import sqlite3
conn = sqlite3.connect('data/trading.db')
cur = conn.cursor()

# 最近20条 run_log（包含终端输出）
print("=== run_log 最近20条 ===")
cur.execute('SELECT time, message FROM run_log ORDER BY id DESC LIMIT 20')
for r in cur.fetchall():
    print(f"  {r[0]} {r[1][:150]}")

print()

# 今日盈亏按 reason 汇总
print("=== 今日按 reason 汇总 ===")
cur.execute("""
    SELECT reason, COUNT(*), ROUND(SUM(realized_pnl),2), ROUND(SUM(fee),2), ROUND(SUM(net_pnl),2)
    FROM trade_records 
    WHERE DATE(time) = DATE('now', 'localtime')
    GROUP BY reason
    ORDER BY SUM(realized_pnl) ASC
""")
for r in cur.fetchall():
    print(f"  {r[0]:20s}  {r[1]:3d}笔  pnl:{r[2]:>+8.2f}  fee:{r[3]:>7.2f}  net:{r[4]:>+8.2f}")

print()

# 当前持仓
print("=== 当前未平仓快捞持仓 ===")
cur.execute("SELECT * FROM fast_positions WHERE closed=0")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]} {r[1]} 入场:{r[2]} qty:{r[3]:.0f} 开仓:{r[5]}")
else:
    print("  (无)")

print()

# 今日总盈亏
cur.execute("""
    SELECT ROUND(SUM(realized_pnl),2), ROUND(SUM(fee),2), ROUND(SUM(net_pnl),2)
    FROM trade_records 
    WHERE DATE(time) = DATE('now', 'localtime')
""")
r = cur.fetchone()
print(f"今日总盈亏: pnl={r[0]:+.2f}  fee={r[1]:.2f}  net={r[2]:+.2f}")

conn.close()
