"""查询最近亏损单"""
import sqlite3, os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db = os.path.join(BASE, "data", "trading.db")
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

# 最近亏损单
rows = conn.execute("""
    SELECT time, symbol, side, reason, realized_pnl, fee, net_pnl,
           entry_price, exit_price, qty, slippage, entry_mode
    FROM trade_records
    WHERE reason != 'open' AND realized_pnl < 0
    ORDER BY time DESC LIMIT 20
""").fetchall()

print(f"{'时间':<22} {'币种':<14} {'方向':<7} {'原因':<18} {'盈亏':>9} {'入场价':>11} {'出场价':>11} {'数量':>8} {'滑点':>6}")
print("-" * 115)
for r in rows:
    d = dict(r)
    pnl = d["realized_pnl"]
    print(f"{d['time'][:19]:<22} {d['symbol']:<14} {d['side']:<7} {d['reason']:<18} {pnl:>+9.2f} {d['entry_price'] or 0:>11.4f} {d['exit_price'] or 0:>11.4f} {d['qty']:>8.0f} {d['slippage']:>6.4f}")

# 亏损原因分布
print("\n近2天亏损原因分布:")
rows_all = conn.execute("""
    SELECT reason, COUNT(*) as cnt, SUM(realized_pnl) as total_loss,
           AVG(ABS(realized_pnl)) as avg_loss, MIN(realized_pnl) as worst_loss
    FROM trade_records
    WHERE reason != 'open' AND realized_pnl < 0
      AND time >= datetime('now', '-2 days')
    GROUP BY reason ORDER BY total_loss
""").fetchall()
print(f"{'原因':<20} {'笔数':>5} {'总亏损':>10} {'平均亏损':>9} {'最差单':>9}")
print("-" * 55)
for r in rows_all:
    d = dict(r)
    print(f"{d['reason']:<20} {d['cnt']:>5} {d['total_loss']:>+9.2f} {d['avg_loss']:>8.2f} {d['worst_loss']:>+8.2f}")

# 检查亏损单的时间间隔 - 是否集中在某时段
print("\n亏损单时间分布（近2天每6小时段）:")
rows_time = conn.execute("""
    SELECT
        CASE
            WHEN time >= datetime('now', '-6 hours') THEN '最近6h'
            WHEN time >= datetime('now', '-12 hours') THEN '6-12h前'
            WHEN time >= datetime('now', '-18 hours') THEN '12-18h前'
            WHEN time >= datetime('now', '-24 hours') THEN '18-24h前'
            WHEN time >= datetime('now', '-30 hours') THEN '24-30h前'
            WHEN time >= datetime('now', '-36 hours') THEN '30-36h前'
            WHEN time >= datetime('now', '-42 hours') THEN '36-42h前'
            ELSE '42-48h前'
        END as period,
        COUNT(*) as cnt,
        SUM(realized_pnl) as total_loss,
        AVG(ABS(realized_pnl)) as avg_loss
    FROM trade_records
    WHERE reason != 'open' AND realized_pnl < 0
      AND time >= datetime('now', '-2 days')
    GROUP BY period ORDER BY time DESC
""").fetchall()
print(f"{'时间段':<14} {'笔数':>5} {'总亏损':>10} {'平均亏损':>9}")
print("-" * 40)
for r in rows_time:
    d = dict(r)
    print(f"{d['period']:<14} {d['cnt']:>5} {d['total_loss']:>+9.2f} {d['avg_loss']:>8.2f}")
