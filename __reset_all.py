"""一键清空所有数据，重新开始"""
import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# 1. 通过 SQL 清空数据库（避免文件被占用）
db_path = os.path.join(DATA_DIR, "trading.db")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    for t in tables:
        conn.execute(f"DELETE FROM {t[0]}")
        print(f"  [清空] 表 {t[0]}")
    conn.commit()
    conn.close()
    print("  [OK] 数据库已清空")
else:
    print(f"  [跳过] {db_path} 不存在")

# 2. 删除缓存文件（旧格式已迁移到 SQLite，但仍保留兼容删除）
for name in ("fast_trade_state.json", "summary_sent_state.json", "square_feeds.json"):
    f = os.path.join(DATA_DIR, name)
    if os.path.exists(f):
        try:
            os.remove(f)
            print(f"  [删除] {f}")
        except Exception as e:
            print(f"  [跳过] {f} ({e})")
    else:
        print(f"  [跳过] {f} 不存在")

# 3. 删除 K 线数据库
kline_db = os.path.join(DATA_DIR, "klines.db")
if os.path.exists(kline_db):
    try:
        conn = sqlite3.connect(kline_db, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        for t in tables:
            conn.execute(f"DELETE FROM {t[0]}")
        conn.commit()
        conn.close()
        print("  [OK] klines.db 已清空")
    except Exception as e:
        print(f"  [跳过] klines.db: {e}")
else:
    print(f"  [跳过] {kline_db} 不存在")

print("\n✅ 所有数据已清空，可以重新开始了。")
