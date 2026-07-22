"""AI复盘分析存储"""
import json
import os
from datetime import datetime

ANALYSIS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "analysis_summary.jsonl")


def save_summary_analysis(period_label: str, stats: dict, ai_analysis: dict):
    if not ai_analysis:
        return
    entry = {
        "time": datetime.now().isoformat(),
        "period": period_label,
        "stats": {
            "total_trades": stats["total_trades"],
            "win_rate": stats["win_rate"],
            "total_pnl": stats["total_pnl"],
        },
        "analysis": ai_analysis,
    }
    os.makedirs(os.path.dirname(ANALYSIS_FILE), exist_ok=True)
    with open(ANALYSIS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
