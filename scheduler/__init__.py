"""
调度器 — 3个并行循环的启动入口

  快捞监控(2分钟)  趋势采集+AI摘要(30分钟)  汇总报表(1h/3h/6h/12h/24h)
"""
import time
import threading
from datetime import datetime
from utils.logger import patch_print, flush_log
from utils.db import init_db
from utils.trade.stats import reconcile_trades

FAST_MONITOR_INTERVAL = 120   # 快捞监测：2分钟


def run_forever():
    from scheduler.loops import (
        summary_loop, fast_loop, trend_loop,
    )
    from scheduler.conditions import check_prerequisites, print_status

    init_db()
    patch_print()
    print("=" * 60)
    print("  币安 U本位合约 自动化交易系统")
    print("  快捞监测循环:    每 2 分钟（监测500+币种，涨6%触发追涨杀跌）")
    print("  趋势采集循环:    每 30 分钟（广场+X动态→AI摘要→微信通知）")
    print("  汇总报表循环:    每 60 秒检查（到点发送 1h/3h/6h/12h/24h 到微信）")
    print("  平仓流水:        SQLite (data/trading.db)")
    print(f"  启动时间: {datetime.now().isoformat()}")
    print("=" * 60)

    if not check_prerequisites():
        print("\n[警告] 前置条件不满足，系统退出。")
        return

    try:
        from utils.db import _get_trade_conn
        conn = _get_trade_conn()
        row = conn.execute("SELECT MAX(time) FROM trade_records").fetchone()
        last_time = row[0] if row and row[0] else None
        if last_time:
            from datetime import datetime as dt
            last_dt = dt.fromisoformat(last_time)
            since_ts = last_dt.timestamp() - 60
        else:
            since_ts = 1782140400.0  # 首轮：2026-07-22 03:00:00 CST
        reconcile_trades(since=since_ts)
    except Exception as e:
        print(f"[对账] 自动对账异常: {e}")

    threads = [
        threading.Thread(target=fast_loop, daemon=True, name="Fast-Trade"),
        threading.Thread(target=trend_loop, daemon=True, name="Trend-Collector"),
        threading.Thread(target=summary_loop, daemon=True, name="Summary-Report"),
    ]
    for t in threads:
        t.start()

    print("\n三个循环已启动，按 Ctrl+C 停止。\n")
    time.sleep(1)
    print_status()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[停止] 收到中断信号，系统停止。")
        flush_log()
