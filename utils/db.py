"""
数据库层 — SQLite 存储（交易流水 + 运行日志 + 复盘 统一管理）
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TRADE_DB = os.path.join(DATA_DIR, "trading.db")
# 日志已合并到 trading.db（原 run_log.db 已废弃）

_local = threading.local()


def _get_trade_conn() -> sqlite3.Connection:
    if not hasattr(_local, "trade_conn") or _local.trade_conn is None:
        _local.trade_conn = sqlite3.connect(TRADE_DB, timeout=10)
        _local.trade_conn.row_factory = sqlite3.Row
        _local.trade_conn.execute("PRAGMA journal_mode=WAL")
        _local.trade_conn.execute("PRAGMA busy_timeout=10000")
    return _local.trade_conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)

    # 交易流水
    conn = _get_trade_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
            reason TEXT NOT NULL, realized_pnl REAL DEFAULT 0,
            fee REAL DEFAULT 0, net_pnl REAL DEFAULT 0,
            qty REAL DEFAULT 0, entry_price REAL DEFAULT 0,
            exit_price REAL DEFAULT 0, is_partial INTEGER DEFAULT 0,
            order_id INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_time ON trade_records(time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_symbol ON trade_records(symbol)")
    # 新增列（幂等：已存在时忽略）
    try:
        conn.execute("ALTER TABLE trade_records ADD COLUMN slippage REAL DEFAULT 0")
    except Exception:
        pass  # 列已存在
    try:
        conn.execute("ALTER TABLE trade_records ADD COLUMN entry_mode TEXT DEFAULT ''")
    except Exception:
        pass  # 列已存在

    # 资金费率流水
    conn.execute("""
        CREATE TABLE IF NOT EXISTS funding_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            funding_rate REAL DEFAULT 0,
            payment REAL DEFAULT 0,
            mark_price REAL DEFAULT 0,
            position_qty REAL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_funding_time ON funding_records(time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_funding_symbol ON funding_records(symbol)")

    # 复盘
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL, period TEXT NOT NULL,
            total_trades INTEGER DEFAULT 0, total_pnl REAL DEFAULT 0,
            win_rate REAL DEFAULT 0, long_short TEXT DEFAULT '',
            data_source TEXT DEFAULT '', used_square INTEGER DEFAULT 0,
            ai_root_cause TEXT DEFAULT '', ai_suggestion TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_time ON trade_reviews(time)")
    conn.commit()
    _migrate_trade_jsonl(conn)

    # 运行日志（写入 trading.db）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL, message TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_time ON run_log(time)")
    conn.commit()
    _migrate_log_jsonl(conn)


# ==================== 迁移旧数据（幂等） ====================

def _migrate_trade_jsonl(conn: sqlite3.Connection):
    row = conn.execute("SELECT COUNT(*) as c FROM trade_records").fetchone()
    if row["c"] > 0:
        return
    rec_file = os.path.join(DATA_DIR, "trade_records.jsonl")
    if not os.path.exists(rec_file):
        return
    count = 0
    with open(rec_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                conn.execute("""
                    INSERT INTO trade_records (time, symbol, side, reason, realized_pnl, fee, net_pnl, qty, entry_price, exit_price, is_partial, order_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r.get("time", ""), r.get("symbol", ""), r.get("side", ""),
                    r.get("reason", ""), r.get("realized_pnl", 0), r.get("fee", 0),
                    r.get("net_pnl", 0), r.get("qty", 0), r.get("entry_price", 0),
                    r.get("exit_price", 0), 1 if r.get("is_partial") else 0,
                    r.get("order_id", 0),
                ))
                count += 1
            except Exception:
                pass
    conn.commit()
    if count:
        print(f"[DB迁移] trade_records.jsonl → trading.db: {count} 条")


def _migrate_log_jsonl(conn: sqlite3.Connection):
    row = conn.execute("SELECT COUNT(*) as c FROM run_log").fetchone()
    if row["c"] > 0:
        return
    log_file = os.path.join(DATA_DIR, "run_log.jsonl")
    if not os.path.exists(log_file):
        return
    count = 0
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                conn.execute("INSERT INTO run_log (time, message) VALUES (?, ?)",
                             (r.get("time", ""), r.get("message", "")))
                count += 1
            except Exception:
                pass
    conn.commit()
    if count:
        print(f"[DB迁移] run_log.jsonl → trading.db: {count} 条")


# ==================== 交易流水 ====================

def insert_trade_record(record: dict):
    conn = _get_trade_conn()
    order_id = record.get("order_id", 0)
    # 去重：有 order_id 且已存在时跳过
    if order_id:
        exists = conn.execute(
            "SELECT 1 FROM trade_records WHERE order_id = ? AND reason != 'open' LIMIT 1",
            (order_id,)
        ).fetchone()
        if exists:
            return
    conn.execute("""
        INSERT INTO trade_records (time, symbol, side, reason, realized_pnl, fee, net_pnl, qty, entry_price, exit_price, is_partial, order_id, slippage, entry_mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record.get("time", datetime.now().isoformat()),
        record.get("symbol"), record.get("side"),
        record.get("reason"), record.get("realized_pnl", 0),
        record.get("fee", 0), record.get("net_pnl", 0),
        record.get("qty", 0), record.get("entry_price", 0),
        record.get("exit_price", 0), 1 if record.get("is_partial") else 0,
        order_id, record.get("slippage", 0),
        record.get("entry_mode", ""),
    ))
    conn.commit()


def get_trade_records(limit: int = 50) -> list[dict]:
    conn = _get_trade_conn()
    rows = conn.execute(
        "SELECT * FROM trade_records ORDER BY time DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_trade_records_since(hours: int) -> list[dict]:
    conn = _get_trade_conn()
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT * FROM trade_records WHERE time >= ? AND reason != 'open' ORDER BY id",
        (cutoff,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_closed_trades() -> list[dict]:
    conn = _get_trade_conn()
    rows = conn.execute(
        "SELECT * FROM trade_records WHERE reason != 'open' AND realized_pnl != 0 ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


_BAD_RECONCILE_REASONS = ("补录", "补充", "修复补录")


def calc_period_stats(hours: int) -> dict | None:
    """从DB查询周期统计（排除补录类重复记录）"""
    conn = _get_trade_conn()
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT * FROM trade_records WHERE time >= ? AND reason NOT IN ('open', '补录', '补充', '修复补录') ORDER BY id",
        (cutoff,)
    ).fetchall()
    if not rows:
        return None

    by_reason = {}
    long_count = short_count = 0
    long_pnl = short_pnl = 0.0

    for r in rows:
        d = dict(r)
        reason = d["reason"]
        pnl = d.get("net_pnl")
        if pnl is None:
            pnl = d["realized_pnl"]
        if reason not in by_reason:
            by_reason[reason] = {"count": 0, "win": 0, "loss": 0, "pnl": 0.0, "partial": 0}
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnl"] += pnl
        if d.get("is_partial"):
            by_reason[reason]["partial"] += 1
        if pnl > 0:
            by_reason[reason]["win"] += 1
        else:
            by_reason[reason]["loss"] += 1

        side = d.get("side", "")
        if side == "LONG":
            long_count += 1
            long_pnl += pnl
        elif side == "SHORT":
            short_count += 1
            short_pnl += pnl

    pnl_values = []
    for r in rows:
        v = r["net_pnl"]
        if v is None:
            v = r["realized_pnl"]
        pnl_values.append(v)
    total_pnl = sum(pnl_values)
    win = sum(1 for v in pnl_values if v > 0)
    loss = sum(1 for v in pnl_values if v <= 0)
    total = win + loss
    win_rate = round(win / total * 100, 1) if total > 0 else 0

    reason_labels = {
        "stop_loss": "止损", "trailing_stop": "追踪止盈", "take_profit": "止盈减仓",
        "force_close": "AI强制减仓", "switch": "币种切换", "direction_reverse": "方向反转",
        "fast_tp": "快捞止盈", "fast_sl": "快捞止损", "fast_tp_lock": "快捞浮动锁仓",
        "micro_close": "微型平仓",
        "tp1_rr": "TP1止盈(1:3)", "tp1_full_close": "TP1全平",
        "breakeven_close": "保本止损", "consolidation_close": "盘整全平",
        "no_direction_close": "防耗散平仓", "trend_reversal_close": "趋势反转平仓",
        "stage1_stop": "放养期止损",
    }
    reasons_list = []
    for reason in sorted(by_reason.keys()):
        s = by_reason[reason]
        r_wr = round(s["win"] / (s["win"] + s["loss"]) * 100, 1) if (s["win"] + s["loss"]) > 0 else 0
        reasons_list.append({
            "reason": reason, "label": reason_labels.get(reason, reason),
            "count": s["count"], "win": s["win"], "loss": s["loss"],
            "pnl": round(s["pnl"], 2), "win_rate": r_wr, "partial": s["partial"],
        })

    # 按币种统计
    sym_stats = {}
    for r in rows:
        sym = r["symbol"]
        pnl = r["net_pnl"] or r["realized_pnl"]
        if sym not in sym_stats:
            sym_stats[sym] = {"win": 0, "loss": 0, "pnl": 0.0}
        sym_stats[sym]["pnl"] += pnl
        if pnl > 0:
            sym_stats[sym]["win"] += 1
        else:
            sym_stats[sym]["loss"] += 1
    by_symbol = []
    for sym, s in sorted(sym_stats.items(), key=lambda x: x[1]["pnl"]):
        t = s["win"] + s["loss"]
        by_symbol.append({
            "symbol": sym, "pnl": round(s["pnl"], 2),
            "win": s["win"], "loss": s["loss"], "total": t,
            "win_rate": round(s["win"] / t * 100, 1) if t > 0 else 0,
        })

    return {
        "time": datetime.now().isoformat(), "period_hours": hours,
        "total_trades": total, "win": win, "loss": loss, "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "long_count": long_count, "short_count": short_count,
        "long_pnl": round(long_pnl, 2), "short_pnl": round(short_pnl, 2),
        "by_reason": reasons_list, "by_symbol": by_symbol,
    }


# ==================== 资金费率 ====================

def insert_funding_record(record: dict):
    conn = _get_trade_conn()
    conn.execute("""
        INSERT INTO funding_records (time, symbol, side, funding_rate, payment, mark_price, position_qty)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        record.get("time", datetime.now().isoformat()),
        record.get("symbol", ""), record.get("side", ""),
        record.get("funding_rate", 0), record.get("payment", 0),
        record.get("mark_price", 0), record.get("position_qty", 0),
    ))
    conn.commit()


def get_funding_records(limit: int = 50) -> list[dict]:
    conn = _get_trade_conn()
    rows = conn.execute(
        "SELECT * FROM funding_records ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    result = [dict(r) for r in rows]
    result.reverse()
    return result


def get_total_funding_payment(since: str | None = None) -> float:
    """获取累计资金费率支出（正=支出，负=收入）"""
    conn = _get_trade_conn()
    if since:
        row = conn.execute(
            "SELECT COALESCE(SUM(payment), 0) FROM funding_records WHERE time >= ?",
            (since,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COALESCE(SUM(payment), 0) FROM funding_records").fetchone()
    return row[0]


# ==================== 复盘 ====================

def insert_review(review: dict):
    conn = _get_trade_conn()
    conn.execute("""
        INSERT INTO trade_reviews (time, period, total_trades, total_pnl, win_rate, long_short, data_source, used_square, ai_root_cause, ai_suggestion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        review.get("time", datetime.now().isoformat()),
        review.get("period", ""), review.get("total_trades", 0),
        review.get("total_pnl", 0), review.get("win_rate", 0),
        review.get("long_short", ""), review.get("data_source", ""),
        1 if review.get("used_square") else 0,
        review.get("ai_root_cause", ""), review.get("ai_suggestion", ""),
    ))
    conn.commit()


def get_recent_reviews(n: int = 5) -> list[dict]:
    conn = _get_trade_conn()
    rows = conn.execute(
        "SELECT * FROM trade_reviews ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    result = [dict(r) for r in rows]
    result.reverse()
    return result


# ==================== 运行日志 ====================

def insert_log_entry(time_str: str, message: str):
    conn = _get_trade_conn()
    conn.execute("INSERT INTO run_log (time, message) VALUES (?, ?)", (time_str, message))
    conn.commit()


def bulk_insert_logs(entries: list[dict]):
    conn = _get_trade_conn()
    conn.executemany("INSERT INTO run_log (time, message) VALUES (:time, :message)", entries)
    conn.commit()
