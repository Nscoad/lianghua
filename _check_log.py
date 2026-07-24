import sqlite3
conn = sqlite3.connect('data/trading.db')
cur = conn.cursor()

# 波动率日志频次
import datetime
cur.execute("SELECT time, message FROM run_log WHERE message LIKE '%波动率评估%' ORDER BY id")
rows = cur.fetchall()
print(f"波动率评估总条数: {len(rows)}")
if rows:
    # 显示前5条和后5条的时间
    for r in rows[:5]:
        print(f"  {r[0][:19]} {r[1]}")
    if len(rows) > 10:
        print("  ...")
    for r in rows[-5:]:
        print(f"  {r[0][:19]} {r[1]}")

# 看下最新的日志时间范围
cur.execute("SELECT MIN(time), MAX(time) FROM run_log")
rng = cur.fetchone()
print(f"\nrun_log 时间范围: {rng[0][:19]} ~ {rng[1][:19]}")
print(f"总记录数: {len(rows)} 条波动率评估日志")

conn.close()
