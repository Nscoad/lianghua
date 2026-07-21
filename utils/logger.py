"""日志 — 写 trading.db.run_log"""
import sys
import builtins
import time
from datetime import datetime
from utils.db import bulk_insert_logs

_original_print = builtins.print
_buffer = []
_last_flush = time.time()


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _write_log_entry(msg: str):
    _buffer.append({"time": datetime.now().isoformat(), "message": msg})


def _flush_buffer():
    global _buffer, _last_flush
    if not _buffer:
        return
    try:
        bulk_insert_logs(_buffer)
    except Exception:
        pass
    _buffer = []
    _last_flush = time.time()


def timestamped_print(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    _original_print(f"[{_timestamp()}] {msg}", **kwargs)
    _write_log_entry(msg)
    if len(_buffer) >= 100 or (time.time() - _last_flush) >= 10:
        _flush_buffer()


def patch_print():
    builtins.print = timestamped_print
    _original_print(f"[{_timestamp()}] [日志] print 已替换 -> trading.db")


def flush_log():
    _flush_buffer()
