"""回测报告生成"""
from datetime import datetime


def print_report(trades: list, symbol: str, interval: str, days: int):
    if not trades:
        print("[回测] 无交易记录")
        return

    total_pnl = sum(t["pnl"] for t in trades)
    win = sum(1 for t in trades if t["pnl"] > 0)
    loss = sum(1 for t in trades if t["pnl"] <= 0)
    total = win + loss
    win_rate = win / total * 100 if total > 0 else 0

    # 原因分布
    reasons = {}
    for t in trades:
        r = t["reason"]
        if r not in reasons:
            reasons[r] = {"count": 0, "win": 0, "loss": 0, "pnl": 0.0}
        reasons[r]["count"] += 1
        reasons[r]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            reasons[r]["win"] += 1
        else:
            reasons[r]["loss"] += 1

    max_pnl = max(t["pnl"] for t in trades) if trades else 0
    min_pnl = min(t["pnl"] for t in trades) if trades else 0
    largest_win_pct = max_pnl / trades[0]["margin"] * 100 if trades[0]["margin"] > 0 else 0
    largest_loss_pct = min_pnl / trades[0]["margin"] * 100 if trades[0]["margin"] > 0 else 0

    initial_margin = trades[0]["margin"]
    final_margin = initial_margin + total_pnl
    roi = total_pnl / initial_margin * 100 if initial_margin > 0 else 0

    print(f"\n{'='*60}")
    print(f"  回测报告: {symbol} | {interval} | {days}天")
    print(f"{'='*60}")
    print(f"  初始保证金:     {initial_margin:.2f} USDT")
    print(f"  最终保证金:     {final_margin:.2f} USDT")
    print(f"  ROI:            {roi:+.2f}%")
    print(f"  总交易:         {total} 笔")
    print(f"  净盈亏:         {total_pnl:+.2f} USDT")
    print(f"  胜率:           {win}胜/{loss}败 ({win_rate:.1f}%)")
    print(f"  最大单笔盈利:   {max_pnl:+.2f} USDT ({largest_win_pct:.1f}%)")
    print(f"  最大单笔亏损:   {min_pnl:+.2f} USDT ({largest_loss_pct:.1f}%)")
    print(f"\n  原因分布:")
    for reason, s in sorted(reasons.items(), key=lambda x: x[1]["pnl"]):
        wr = s["win"] / (s["win"] + s["loss"]) * 100 if (s["win"] + s["loss"]) > 0 else 0
        label = {"stop_loss": "止损", "take_profit": "止盈减仓", "close": "尾仓平"}.get(reason, reason)
        print(f"    {label:<10} {s['count']:>3}次 | {s['pnl']:+8.2f} USDT | 胜率{wr:.0f}%")

    print(f"\n  最近10笔交易:")
    for t in trades[-10:]:
        ts = t["time"]
        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts / 1000)
        print(f"    {ts.strftime('%m-%d %H:%M')} | {t['side']:<5} | {t['reason']:<10} | 入场:{t['entry']:.6f} | 出场:{t['exit']:.6f} | PnL:{t['pnl']:+7.2f}")
    print(f"{'='*60}\n")
