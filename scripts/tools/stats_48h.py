"""查询过去48小时交易统计"""
import sqlite3, os, sys
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "trading.db")
BAD_REASONS = ("open", "补录", "补充", "修复补录")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

cutoff = (datetime.now() - timedelta(hours=48)).isoformat()

# ========== 交易记录 ==========
rows = conn.execute(
    "SELECT * FROM trade_records WHERE time >= ? AND reason NOT IN ('open', '补录', '补充', '修复补录') ORDER BY id",
    (cutoff,)
).fetchall()

records = [dict(r) for r in rows]

print("=" * 70)
print(f"📊 过去48小时交易统计（自 {cutoff}）")
print("=" * 70)

if not records:
    print("暂无记录")
else:
    total = len(records)

    # 总盈亏
    pnl_values = []
    for r in records:
        v = r.get("net_pnl")
        if v is None:
            v = r["realized_pnl"]
        pnl_values.append(v)

    total_pnl = sum(pnl_values)
    wins = sum(1 for v in pnl_values if v > 0)
    losses = sum(1 for v in pnl_values if v <= 0)
    win_rate = round(wins / total * 100, 1) if total else 0

    best = max(records, key=lambda r: r.get("net_pnl") or r["realized_pnl"])
    worst = min(records, key=lambda r: r.get("net_pnl") or r["realized_pnl"])
    best_pnl = best.get("net_pnl") or best["realized_pnl"]
    worst_pnl = worst.get("net_pnl") or worst["realized_pnl"]

    print(f"\n📈 总交易数:    {total}")
    print(f"💰 总盈亏:      {total_pnl:+.2f} USDT")
    print(f"🎯 胜率:        {win_rate}% ({wins}胜 / {losses}负)")
    print(f"🏆 最佳交易:    {best['symbol']} {best['side']} {best['reason']} {best_pnl:+.2f} USDT ({best['time']})")
    print(f"💀 最差交易:    {worst['symbol']} {worst['side']} {worst['reason']} {worst_pnl:+.2f} USDT ({worst['time']})")

    # 按原因细分
    print(f"\n{'─' * 60}")
    print("📂 按原因细分:")
    print(f"{'原因':<24} {'数量':>6} {'胜':>5} {'负':>5} {'盈亏':>12}")
    print(f"{'─' * 60}")
    by_reason = {}
    for r in records:
        reason = r["reason"]
        pnl = r.get("net_pnl") or r["realized_pnl"]
        if reason not in by_reason:
            by_reason[reason] = {"count": 0, "win": 0, "loss": 0, "pnl": 0.0}
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnl"] += pnl
        if pnl > 0:
            by_reason[reason]["win"] += 1
        else:
            by_reason[reason]["loss"] += 1
    for reason, s in sorted(by_reason.items(), key=lambda x: x[1]["pnl"], reverse=True):
        print(f"{reason:<24} {s['count']:>6} {s['win']:>5} {s['loss']:>5} {s['pnl']:>+11.2f}")

    # 按币种细分
    print(f"\n{'─' * 60}")
    print("📂 按币种细分:")
    print(f"{'币种':<12} {'数量':>6} {'胜':>5} {'负':>5} {'胜率':>7} {'盈亏':>12}")
    print(f"{'─' * 60}")
    by_symbol = {}
    for r in records:
        sym = r["symbol"]
        pnl = r.get("net_pnl") or r["realized_pnl"]
        if sym not in by_symbol:
            by_symbol[sym] = {"count": 0, "win": 0, "loss": 0, "pnl": 0.0}
        by_symbol[sym]["count"] += 1
        by_symbol[sym]["pnl"] += pnl
        if pnl > 0:
            by_symbol[sym]["win"] += 1
        else:
            by_symbol[sym]["loss"] += 1
    for sym, s in sorted(by_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = round(s["win"] / s["count"] * 100, 1) if s["count"] else 0
        print(f"{sym:<12} {s['count']:>6} {s['win']:>5} {s['loss']:>5} {wr:>6.1f}% {s['pnl']:>+11.2f}")

    # 多空统计
    long_count = sum(1 for r in records if r.get("side") == "LONG")
    short_count = sum(1 for r in records if r.get("side") == "SHORT")
    long_pnl = sum(r.get("net_pnl") or r["realized_pnl"] for r in records if r.get("side") == "LONG")
    short_pnl = sum(r.get("net_pnl") or r["realized_pnl"] for r in records if r.get("side") == "SHORT")
    long_wins = sum(1 for r in records if r.get("side") == "LONG" and (r.get("net_pnl") or r["realized_pnl"]) > 0)
    short_wins = sum(1 for r in records if r.get("side") == "SHORT" and (r.get("net_pnl") or r["realized_pnl"]) > 0)

    print(f"\n{'─' * 60}")
    print("🔄 多空统计:")
    print(f"{'方向':<8} {'数量':>6} {'胜':>5} {'负':>5} {'胜率':>7} {'盈亏':>12}")
    print(f"{'─' * 60}")
    l_wr = round(long_wins / long_count * 100, 1) if long_count else 0
    s_wr = round(short_wins / short_count * 100, 1) if short_count else 0
    print(f"{'LONG':<8} {long_count:>6} {long_wins:>5} {long_count - long_wins:>5} {l_wr:>6.1f}% {long_pnl:>+11.2f}")
    print(f"{'SHORT':<8} {short_count:>6} {short_wins:>5} {short_count - short_wins:>5} {s_wr:>6.1f}% {short_pnl:>+11.2f}")

    # 总手续费 & 总滑点
    total_fees = sum(r.get("fee", 0) or 0 for r in records)
    total_slippage = sum(r.get("slippage", 0) or 0 for r in records)
    print(f"\n💸 总手续费:    {total_fees:.4f} USDT")
    print(f"📉 总滑点:      {total_slippage:.4f} USDT")

# ========== 资金费率 ==========
print(f"\n{'=' * 70}")
print("💲 资金费率记录（过去48小时）")
print("=" * 70)
fund_rows = conn.execute(
    "SELECT * FROM funding_records WHERE time >= ? ORDER BY id", (cutoff,)
).fetchall()
fund_records = [dict(r) for r in fund_rows]
if fund_records:
    total_payment = sum(r.get("payment", 0) or 0 for r in fund_records)
    print(f"总资金费率支出: {total_payment:+.6f} USDT（正=支出，负=收入）")
    print(f"笔数: {len(fund_records)}")
    print()
    print(f"{'时间':<22} {'币种':<10} {'方向':<6} {'费率':>10} {'支付':>14}")
    print(f"{'─' * 66}")
    for r in fund_records:
        print(f"{r['time']:<22} {r['symbol']:<10} {r['side']:<6} {r['funding_rate']:>10.6f} {r['payment']:>+13.6f}")
else:
    print("暂无记录")


# ========== 最近20条交易 ==========
print(f"\n{'=' * 70}")
print("📋 最近20条交易记录")
print("=" * 70)
recent = conn.execute(
    "SELECT * FROM trade_records WHERE reason NOT IN ('open', '补录', '补充', '修复补录') ORDER BY id DESC LIMIT 20",
).fetchall()
recent = [dict(r) for r in recent]
recent.reverse()

if recent:
    print(f"{'时间':<22} {'币种':<10} {'方向':<6} {'原因':<20} {'盈亏':>10} {'手续费':>10}")
    print(f"{'─' * 82}")
    for r in recent:
        pnl = r.get("net_pnl") or r["realized_pnl"]
        fee = r.get("fee", 0) or 0
        print(f"{r['time']:<22} {r['symbol']:<10} {r['side']:<6} {r['reason']:<20} {pnl:>+9.2f} {fee:>9.4f}")
else:
    print("暂无记录")

conn.close()
