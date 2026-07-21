"""AI复盘分析存储"""
import json
import os
from datetime import datetime

ANALYSIS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "analysis_summary.jsonl")


def save_summary_analysis(period_label: str, stats: dict, ai_analysis: dict):
    if not ai_analysis:
        return

    now = datetime.now()
    now_hour_key = now.strftime("%Y-%m-%dT%H")  # 小时级去重

    # 读取最后一条同period记录，避免同一小时内重复写入
    os.makedirs(os.path.dirname(ANALYSIS_FILE), exist_ok=True)
    if os.path.exists(ANALYSIS_FILE):
        try:
            with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    pass  # 读到末尾
                last_line = line.strip() if line else None
            if last_line:
                last = json.loads(last_line)
                if last.get("period") == period_label:
                    last_hour = last.get("time", "")[:13]  # "2026-07-21T03"
                    if last_hour == now_hour_key:
                        return  # 同一小时已有记录，跳过
        except Exception:
            pass

    record = {
        "time": now.isoformat(),
        "period": period_label,
        "stats": {
            "total_trades": stats.get("total_trades", 0),
            "total_pnl": stats.get("total_pnl", 0),
            "win_rate": stats.get("win_rate", 0),
            "win": stats.get("win", 0), "loss": stats.get("loss", 0),
            "long_count": stats.get("long_count", 0), "short_count": stats.get("short_count", 0),
            "long_pnl": stats.get("long_pnl", 0), "short_pnl": stats.get("short_pnl", 0),
            "period_hours": stats.get("period_hours", 0),
        },
        "analysis": {
            "root_cause": ai_analysis.get("root_cause", ""),
            "details": ai_analysis.get("details", ""),
            "suggestions": ai_analysis.get("suggestions", ""),
            "adjustment": ai_analysis.get("adjustment", ""),
        },
    }
    with open(ANALYSIS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    rc = ai_analysis.get("root_cause", "")
    sg = ai_analysis.get("suggestions", "")
    print(f"\n[汇总AI分析] {period_label} — {rc}")
    if sg:
        print(f"  [建议] {sg}")
