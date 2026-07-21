"""
调度器 — 5个并行循环的启动入口

  风险监控(1.5s)  汇总报表(1h/3h/6h/12h/24h)  全场监控(1h)
"""
import sys
import time
import threading
from datetime import datetime
from utils.logger import patch_print, flush_log
from utils.db import init_db
from utils.trade_stats import reconcile_trades

RISK_INTERVAL = 1.5
MONITOR_INTERVAL = 3600
FAST_MONITOR_INTERVAL = 120  # 快捞监测：2分钟


def run_forever():
    from scheduler.loops import (
        risk_loop, summary_loop, monitor_loop, fast_loop, trend_loop,
    )
    from scheduler.conditions import check_prerequisites, print_status

    init_db()
    patch_print()
    print("=" * 60)
    print("  币安 U本位合约 自动化交易（5x 杠杆）")
    print(f"  风险监控循环:    每 {RISK_INTERVAL} 秒（止损15%/TP1止盈45%/保本/防耗散）")
    print("  汇总报表循环:    每 60 秒检查（到点发送 1h/3h/6h/12h/24h 到微信）")
    print("  全场币种监控:    每 1 小时（检测异常涨幅）")
    print("  快捞循环:        每 2 分钟（监测500+币种，涨6%触发小仓追涨杀跌）")
    print("  趋势采集循环:     每 15 分钟（广场热门 + X.com 趋势信息）")
    print("  平仓流水:        SQLite (data/trading.db)")
    print(f"  启动时间: {datetime.now().isoformat()}")
    print("=" * 60)

    if not check_prerequisites():
        print("\n[警告] 前置条件不满足，系统退出。")
        return

    try:
        # 对账起点：当前时间（只补录启动后新成交）
        since_ts = time.time()
        reconcile_trades(since=since_ts)
    except Exception as e:
        print(f"[对账] 自动对账异常: {e}")

    threads = [
        threading.Thread(target=risk_loop, daemon=True, name="Risk-Monitor"),
        threading.Thread(target=summary_loop, daemon=True, name="Summary-Report"),
        threading.Thread(target=monitor_loop, daemon=True, name="Market-Monitor"),
        threading.Thread(target=fast_loop, daemon=True, name="Fast-Trade"),
        threading.Thread(target=trend_loop, daemon=True, name="Trend-Collector"),
    ]
    for t in threads:
        t.start()

    print("\n五个循环已启动，按 Ctrl+C 停止。\n")
    time.sleep(1)
    print_status()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[停止] 收到中断信号，系统停止。")
        flush_log()


def run_once():
    from collector.square import ensure_chrome_debug
    from strategy.risk_monitor import check_risk_once

    init_db()
    patch_print()
    print(">>> 执行单轮风险检查 <<<")
    if not ensure_chrome_debug():
        print("[错误] Chrome 调试模式不可用。")
        return
    print("\n[风险检查]")
    check_risk_once(silent=False)
    print("\n单次检查完成")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    run_forever() if mode == "forever" else run_once()
