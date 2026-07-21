from utils.trade_stats import calc_period_stats
from utils.trade_analysis import ANALYSIS_FILE
import json, os

for h in [1, 3, 6]:
    stats = calc_period_stats(h)
    if stats:
        print(f"=== 近{h}小时 ===")
        print(f"总交易: {stats['total_trades']} | 净盈亏: {stats['total_pnl']:+.2f} USDT")
        print(f"胜率: {stats['win']}胜/{stats['loss']}败 ({stats['win_rate']}%)")
        print(f"多空: {stats['long_count']}多 / {stats['short_count']}空")
        print(f"多单盈亏: {stats['long_pnl']:+.2f} | 空单盈亏: {stats['short_pnl']:+.2f}")
        if stats.get('by_reason'):
            for r in stats['by_reason']:
                print(f"  {r['label']}: {r['count']}次 {r['pnl']:+.2f} USDT")
        print()

print("=== AI复盘分析 ===")
if os.path.exists(ANALYSIS_FILE):
    with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines[-3:]:
        if line.strip():
            r = json.loads(line)
            print(f"[{r['period']}] {r['time'][:19]}")
            print(f"  根因: {r['analysis'].get('root_cause','')}")
            print(f"  建议: {r['analysis'].get('suggestions','')}")
            print()
