"""
状态持久化 — 交易状态 + 冷却 + 汇总发送记录 + 心跳

复用 utils.db._get_trade_conn() 统一连接管理。
基于 SQLite UPSERT + 事务，提供原子写入。
首次调用时自动初始化表结构、自动从旧 JSON 迁移。
"""
import json
import os
from datetime import datetime
from utils.db import _get_trade_conn


# ==================== 表初始化（惰性） ====================

_TABLES_INIT_SQL = """
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

CREATE TABLE IF NOT EXISTS heartbeat (
    task_name TEXT PRIMARY KEY,
    last_run_time TEXT NOT NULL,
    last_status TEXT DEFAULT 'ok'
);
"""

_tables_initialized = False


def _ensure_tables():
    global _tables_initialized
    if _tables_initialized:
        return
    conn = _get_trade_conn()
    conn.executescript(_TABLES_INIT_SQL)
    conn.commit()
    _tables_initialized = True


# ==================== 心跳 ====================


def beat(task_name: str, status: str = "ok"):
    """记录任务心跳时间"""
    _ensure_tables()
    conn = _get_trade_conn()
    conn.execute("""
        INSERT INTO heartbeat (task_name, last_run_time, last_status)
        VALUES (?, ?, ?)
        ON CONFLICT(task_name) DO UPDATE SET
            last_run_time = excluded.last_run_time,
            last_status = excluded.last_status
    """, (task_name, datetime.now().isoformat(), status))
    conn.commit()


def get_heartbeats() -> list[dict]:
    """获取所有任务心跳"""
    _ensure_tables()
    conn = _get_trade_conn()
    conn.row_factory = None  # 恢复默认，避免 Row 对象
    rows = conn.execute("SELECT * FROM heartbeat").fetchall()
    return [
        {"task_name": r[0], "last_run_time": r[1], "last_status": r[2]}
        for r in rows
    ]


# ==================== 快捞状态（UPSERT 并发安全） ====================


def load_fast_state() -> dict:
    """加载快捞状态，返回 {'positions': {...}, 'cooling': {...}}"""
    _migrate_fast_state_once()
    _ensure_tables()
    conn = _get_trade_conn()

    positions = {}
    for r in conn.execute("SELECT * FROM fast_positions"):
        # _get_trade_conn 的 row_factory = sqlite3.Row
        d = dict(r)
        sym = d.pop("symbol")
        d["closed"] = bool(d["closed"])
        positions[sym] = d

    cooling = {}
    for r in conn.execute("SELECT * FROM fast_cooling"):
        cooling[r["symbol"]] = r["expires"]

    return {"positions": positions, "cooling": cooling}


def save_fast_state(state: dict):
    """
    原子保存快捞状态。

    - 存在的仓位 → UPSERT
    - 已移除的仓位 → DELETE
    - 全部在单个事务内完成
    """
    _ensure_tables()
    conn = _get_trade_conn()

    positions = state.get("positions", {})
    for sym, p in positions.items():
        conn.execute("""
            INSERT INTO fast_positions (symbol, side, entry_price, qty, margin, open_time, closed, profit_floor, highest_profit_pct)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                side = excluded.side,
                entry_price = excluded.entry_price,
                qty = excluded.qty,
                margin = excluded.margin,
                open_time = excluded.open_time,
                closed = excluded.closed,
                profit_floor = excluded.profit_floor,
                highest_profit_pct = excluded.highest_profit_pct
        """, (
            sym, p["side"], p["entry_price"], p["qty"],
            p.get("margin", 0), p.get("open_time", ""),
            1 if p.get("closed") else 0,
            p.get("profit_floor", 0.0), p.get("highest_profit_pct", 0.0),
        ))

    # 清理已移除的仓位
    active_symbols = list(positions.keys())
    if active_symbols:
        placeholders = ",".join("?" for _ in active_symbols)
        conn.execute(f"DELETE FROM fast_positions WHERE symbol NOT IN ({placeholders})", active_symbols)
    else:
        conn.execute("DELETE FROM fast_positions")

    # 冷却 — 同样 UPSERT + 清理
    cooling = state.get("cooling", {})
    for sym, expires in cooling.items():
        conn.execute("""
            INSERT INTO fast_cooling (symbol, expires) VALUES (?,?)
            ON CONFLICT(symbol) DO UPDATE SET expires = excluded.expires
        """, (sym, int(expires)))

    active_cooling = list(cooling.keys())
    if active_cooling:
        placeholders = ",".join("?" for _ in active_cooling)
        conn.execute(f"DELETE FROM fast_cooling WHERE symbol NOT IN ({placeholders})", active_cooling)
    else:
        conn.execute("DELETE FROM fast_cooling")

    conn.commit()


# ==================== 汇总报表发送状态（UPSERT 并发安全） ====================


def load_summary_sent() -> dict[int, int]:
    """加载汇总报表发送记录 {cycle_hours: last_sent_timestamp}"""
    _migrate_summary_state_once()
    _ensure_tables()
    conn = _get_trade_conn()

    result = {}
    for r in conn.execute("SELECT * FROM summary_sent"):
        result[r["cycle_hours"]] = r["sent_time"]
    return result


def save_summary_sent(cycle: dict[int, int]):
    """原子保存汇总报表发送记录"""
    _ensure_tables()
    conn = _get_trade_conn()

    # UPSERT 所有
    for k, v in cycle.items():
        conn.execute("""
            INSERT INTO summary_sent (cycle_hours, sent_time) VALUES (?,?)
            ON CONFLICT(cycle_hours) DO UPDATE SET sent_time = excluded.sent_time
        """, (int(k), int(v)))

    # 清理已不存在的
    active = [int(k) for k in cycle.keys()]
    if active:
        placeholders = ",".join("?" for _ in active)
        conn.execute(f"DELETE FROM summary_sent WHERE cycle_hours NOT IN ({placeholders})", active)
    else:
        conn.execute("DELETE FROM summary_sent")

    conn.commit()


# ==================== JSON 迁移（一次性） ====================

_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_migrated_flag: set[str] = set()


def _migrate_fast_state_once():
    if "fast" in _migrated_flag:
        return

    fp = os.path.join(_data_dir, "fast_trade_state.json")
    if not os.path.exists(fp):
        _migrated_flag.add("fast")
        return

    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        _migrated_flag.add("fast")
        return

    # 旧格式（单仓位）→ 多仓位格式
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

    save_fast_state(data)

    try:
        os.remove(fp)
        print("[状态迁移] fast_trade_state.json → SQLite ✅")
    except Exception:
        pass

    _migrated_flag.add("fast")


def _migrate_summary_state_once():
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
