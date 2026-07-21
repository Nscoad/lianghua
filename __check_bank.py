"""复制 DB 再读"""
import shutil, os, sqlite3

src = os.path.join("data", "trading.db")
dst = os.path.join("data", "_tmp_read.db")

if os.path.exists(dst):
    os.remove(dst)

try:
    shutil.copy2(src, dst)
    conn = sqlite3.connect(dst)
    conn.execute("PRAGMA journal_mode=DELETE")

    # 最新100条日志
    rows = conn.execute(
        "SELECT time, message FROM run_log ORDER BY id DESC LIMIT 100"
    ).fetchall()
    print(f"日志总数: 最新100条")
    print("=" * 100)
    for r in reversed(rows):
        print(f"{r[0]}  {r[1][:200]}")

    # 交易记录
    rows2 = conn.execute(
        "SELECT time, symbol, side, reason, realized_pnl, qty, entry_price, exit_price FROM trade_records ORDER BY id DESC LIMIT 20"
    ).fetchall()
    print(f"\n\n交易记录 ({len(rows2)} 条):")
    print("=" * 100)
    for r in rows2:
        print(f"{r[0]}  {r[1]:<10}  {r[2]:>5}  {r[3]:<18}  pnl={r[4]:+.2f}  qty={r[5]}  entry={r[6]}  exit={r[7]}")

    conn.close()
    os.remove(dst)
except Exception as e:
    print(f"错误: {e}")
