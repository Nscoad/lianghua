"""共享状态 — 汇总报表发送状态持久化（SQLite）"""
from utils.state import load_summary_sent, save_summary_sent


def _load_summary_sent_cycle() -> dict[int, int]:
    return load_summary_sent()


def _save_summary_sent_cycle(cycle: dict[int, int]):
    save_summary_sent(cycle)


# 从磁盘加载，保证重启不丢失
summary_sent_cycle: dict[int, int] = _load_summary_sent_cycle()
