"""共享状态 — 汇总报表发送状态持久化"""
import json
import os

_SUMMARY_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "summary_sent_state.json"
)


def _load_summary_sent_cycle() -> dict[int, int]:
    if not os.path.exists(_SUMMARY_STATE_FILE):
        return {}
    try:
        with open(_SUMMARY_STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
    except Exception:
        return {}


def _save_summary_sent_cycle(cycle: dict[int, int]):
    os.makedirs(os.path.dirname(_SUMMARY_STATE_FILE), exist_ok=True)
    try:
        with open(_SUMMARY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(cycle, f, ensure_ascii=False)
    except Exception as e:
        print(f"[状态] 保存汇总状态失败: {e}")


# 从磁盘加载，保证重启不丢失
summary_sent_cycle: dict[int, int] = _load_summary_sent_cycle()
