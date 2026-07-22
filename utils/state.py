"""
状态持久化 — 交易状态 + 冷却 + 汇总报表发送记录

替代 JSON 文件，基于 SQLite 事务提供原子写入。
自动从旧 JSON 文件迁移到 SQLite。
"""
import json
import os
import sqlite3

# 复用 trading.db
TRADE_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trading.db")

STATE_TABLES_INIT = """
CREATE TABLE IF NOT EXISTS fast_positions (
    symbol TEXT PRIMARY KEY,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    qty REAL NOT NULL,
    margin REAL DEFAULT 0,
    open_time TEXT DEFAULT '',
    closed INTEGER DEFAULT 0,
    profit_floor REAL DEFAULT 0.0,
    highest_profit_pct REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS fast_cooling (
    symbol TEXT PRIMARY KEY,
    expires INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS summary_sent (
    cycle_hours INTEGER PRIMARY KEY,
    sent_time INTEGER NOT NULL
);
"""

_JSON_FILES = {
    "fast_trade_state.json": True,
    "summary_sent_state.json": True,
}


def init_state_tables():
    """初始化状态表（由 utils/db.init_db() 调用）"""
    conn = sqlite3.connect(TRADE_DB, timeout=10)
    try:
        conn.executescript(STATE_TABLES_INIT)
        conn.commit()
    finally:
        conn.close()


# ==================== 快捞状态 ====================


def load_fast_state() -> dict:
    """加载快捞状态，返回 {'positions': {...}, 'cooling': {...}}"""
    _migrate_fast_state_once()
    conn = sqlite3.connect(TRADE_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        positions = {}
        for r in conn.execute("SELECT * FROM fast_positions"):
            d = dict(r)
            sym = d.pop("symbol")
            d["closed"] = bool(d["closed"])
            positions[sym] = d

        cooling = {}
        for r in conn.execute("SELECT * FROM fast_cooling"):
            cooling[r["symbol"]] = r["expires"]

        return {"positions": positions, "cooling": cooling}
    finally:
        conn.close()


def save_fast_state(state: dict):
    """原子保存快捞状态（在事务内清空 + 重写）"""
    conn = sqlite3.connect(TRADE_DB, timeout=10)
    try:
        conn.execute("DELETE FROM fast_positions")
        pos_rows = []
        for sym, p in state.get("positions", {}).items():
            pos_rows.append((
                sym, p["side"], p["entry_price"], p["qty"],
                p.get("margin", 0), p.get("open_time", ""),
                1 if p.get("closed") else 0,
                p.get("profit_floor", 0.0), p.get("highest_profit_pct", 0.0),
            ))
        if pos_rows:
            conn.executemany(
                "INSERT INTO fast_positions VALUES (?,?,?,?,?,?,?,?,?)",
                pos_rows,
            )

        conn.execute("DELETE FROM fast_cooling")
        cool_rows = [(s, int(e)) for s, e in state.get("cooling", {}).items()]
        if cool_rows:
            conn.executemany(
                "INSERT INTO fast_cooling VALUES (?,?)", cool_rows,
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==================== 汇总报表发送状态 ====================


def load_summary_sent() -> dict[int, int]:
    """加载汇总报表发送记录 {cycle_hours: last_sent_timestamp}"""
    _migrate_summary_state_once()
    conn = sqlite3.connect(TRADE_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        result = {}
        for r in conn.execute("SELECT * FROM summary_sent"):
            result[r["cycle_hours"]] = r["sent_time"]
        return result
    finally:
        conn.close()


def save_summary_sent(cycle: dict[int, int]):
    """原子保存汇总报表发送记录"""
    conn = sqlite3.connect(TRADE_DB, timeout=10)
    try:
        conn.execute("DELETE FROM summary_sent")
        if cycle:
            conn.executemany(
                "INSERT INTO summary_sent VALUES (?,?)",
                [(int(k), int(v)) for k, v in cycle.items()],
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==================== JSON 迁移（一次性） ====================

_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

_migrated_flag: set[str] = set()


def _migrate_fast_state_once():
    """从 fast_trade_state.json 迁到 SQLite（仅首次）"""
    if "fast" in _migrated_flag:
        return

    fp = os.path.join(_data_dir, "fast_trade_state.json")
    if not os.path.exists(fp):
        # 同时检查表是否有旧数据（支持 SQLite 直接使用）
        conn = sqlite3.connect(TRADE_DB, timeout=10)
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM fast_positions").fetchone()[0]
            if cnt == 0:
                # 无 JSON 也无 SQLite 数据 → 写一条空记录便于后面查询
                pass
        except Exception:
            pass
        finally:
            conn.close()
        _migrated_flag.add("fast")
        return

    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        _migrated_flag.add("fast")
        return

    # 旧格式（单仓位）迁移
    if "symbol" in data and "positions" not in data:
        pos = {}
        sym = data.pop("symbol", None)
        if sym:
            pos[sym] = {
                "entry_price": data.pop("entry_price", 0),
                "side": data.pop("side", "LONG"),
                "qty": data.pop("qty", 0),
                "margin": data.pop("margin", 0),
                "open_time": data.pop("open_time", ""),
                "closed": data.pop("closed", True),
                "profit_floor": data.pop("profit_floor", 0.0),
                "highest_profit_pct": data.pop("highest_profit_pct", 0.0),
            }
        data["positions"] = pos

    # 写入 SQLite
    save_fast_state(data)

    # 删除旧 JSON
    try:
        os.remove(fp)
        print("[状态迁移] fast_trade_state.json → SQLite ✅")
    except Exception:
        pass

    _migrated_flag.add("fast")


def _migrate_summary_state_once():
    """从 summary_sent_state.json 迁到 SQLite（仅首次）"""
    if "summary" in _migrated_flag:
        return

    fp = os.path.join(_data_dir, "summary_sent_state.json")
    if not os.path.exists(fp):
        _migrated_flag.add("summary")
        return

    try:
        with open(fp, "r", encoding="utf-8") as f:
            raw = json.load(f)
            cycle = {int(k): v for k, v in raw.items()}
    except Exception:
        _migrated_flag.add("summary")
        return

    save_summary_sent(cycle)

    try:
        os.remove(fp)
        print("[状态迁移] summary_sent_state.json → SQLite ✅")
    except Exception:
        pass

    _migrated_flag.add("summary")
