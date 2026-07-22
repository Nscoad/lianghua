"""
工具层 — JSON 数据存储与读取
"""
import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FEEDS_FILE = os.path.join(DATA_DIR, "square_feeds.json")
SIGNALS_FILE = os.path.join(DATA_DIR, "trade_signals.json")

os.makedirs(DATA_DIR, exist_ok=True)


def _load_json(file_path: str) -> list:
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_json(file_path: str, data: list):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==================== 广场动态 ====================

FEED_MAX_HOURS = 1  # 动态保留小时数


def load_feeds() -> list[dict]:
    return _load_json(FEEDS_FILE)


def save_feeds(feeds: list[dict]):
    _save_json(FEEDS_FILE, feeds)


def _clean_expired_feeds(feeds: list[dict]) -> list[dict]:
    """删除超过1小时的动态"""
    now = datetime.now()
    kept = []
    removed = 0
    for f in feeds:
        fetched = f.get("fetched_at")
        if fetched:
            try:
                dt = datetime.fromisoformat(fetched)
                hours_diff = (now - dt).total_seconds() / 3600
                if hours_diff >= FEED_MAX_HOURS:
                    removed += 1
                    continue
            except Exception:
                pass
        kept.append(f)
    if removed > 0:
        print(f"[数据清理] 已删除 {removed} 条过期动态（>{FEED_MAX_HOURS}小时）")
    return kept


def add_new_feeds(new_texts: list[str]) -> int:
    existing = load_feeds()
    existing_texts = {item["text"] for item in existing}
    added = 0
    for text in new_texts:
        if text not in existing_texts:
            existing.append({
                "text": text,
                "fetched_at": datetime.now().isoformat(),
            })
            existing_texts.add(text)
            added += 1
    # 删除过期动态
    existing = _clean_expired_feeds(existing)
    save_feeds(existing)
    return added


def get_unanalyzed_feeds() -> list[dict]:
    return [f for f in load_feeds() if not f.get("analyzed")]


def get_active_feed_count(hours: float = 1) -> int:
    """返回过去 N 小时内收集的有效动态条数"""
    now = datetime.now()
    active = 0
    for f in load_feeds():
        fetched = f.get("fetched_at")
        if not fetched:
            continue
        try:
            dt = datetime.fromisoformat(fetched)
            if (now - dt).total_seconds() < hours * 3600:
                active += 1
        except Exception:
            pass
    return active


def mark_feeds_analyzed(feed_indices: list[int]):
    feeds = load_feeds()
    for idx in feed_indices:
        if idx < len(feeds):
            feeds[idx]["analyzed"] = True
            feeds[idx]["analyzed_at"] = datetime.now().isoformat()
    save_feeds(feeds)


# ==================== 交易信号 ====================

SIGNAL_MAX_HOURS = 12


def load_signals() -> list[dict]:
    return _load_json(SIGNALS_FILE)


def save_signal(signal: dict):
    signals = load_signals()
    signals.append(signal)
    # 清理超过12小时的信号
    now = datetime.now()
    kept = []
    for s in signals:
        t = s.get("time") or s.get("fetched_at")
        if t:
            try:
                dt = datetime.fromisoformat(t)
                if (now - dt).total_seconds() < SIGNAL_MAX_HOURS * 3600:
                    kept.append(s)
                # 否则丢弃
            except Exception:
                kept.append(s)
        else:
            kept.append(s)
    _save_json(SIGNALS_FILE, kept)


def get_latest_signal() -> dict | None:
    signals = load_signals()
    return signals[-1] if signals else None
