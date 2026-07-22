"""4个并行循环线程：市场监控、快捞、趋势采集、汇总报表"""
import time
from datetime import datetime
from utils.market.monitor import run_fast_monitor
from scheduler import FAST_MONITOR_INTERVAL
from scheduler.state import (
    summary_sent_cycle, _save_summary_sent_cycle,
)


# ==================== 快捞循环（2分钟） ====================

def fast_loop():
    """每2分钟监测全场币种，涨幅>6%触发快捞"""
    while True:
        try:
            run_fast_monitor()
        except Exception as e:
            print(f"\n[错误] 快捞循环异常: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(FAST_MONITOR_INTERVAL)


# ==================== 趋势采集循环（30分钟） ====================

TREND_INTERVAL = 30 * 60  # 30分钟

_trend_lock = False


def trend_loop():
    """
    每15分钟采集广场热门+X.com动态，AI摘要后发微信通知。
    """
    global _trend_lock
    print("[趋势采集] 线程已启动，等待首次采集...")
    time.sleep(30)  # 启动后等30秒再开始
    while True:
        if _trend_lock:
            time.sleep(10)
            continue
        _trend_lock = True
        try:
            from collector.trend_collector import collect_trends
            from ai.analyzer import run_feed_summary

            # 1. 采集
            collect_trends(max_items_per_source=10)
            # 2. AI摘要并发送微信
            run_feed_summary()
        except Exception as e:
            print(f"\n[错误] 趋势采集循环异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            _trend_lock = False
        time.sleep(TREND_INTERVAL)


# ==================== 汇总报表循环（每分钟检查） ====================

SUMMARY_PERIODS = [(1, "1小时"), (3, "3小时"), (6, "6小时"), (12, "12小时"), (24, "24小时")]


def _check_and_send_summary():
    now = datetime.now()
    current_hour = now.hour
    current_day = now.day

    for hours, label in SUMMARY_PERIODS:
        if hours == 24:
            if not (current_hour == 0 and now.minute >= 5):
                continue
        elif current_hour % hours != 0 or now.minute > 10 or now.minute < 2:
            continue

        cycle_key = hours
        last_sent = summary_sent_cycle.get(cycle_key)
        if hours == 24:
            if last_sent == current_day:
                continue
        else:
            if last_sent == current_hour:
                continue

        try:
            from utils.trade.stats import calc_period_stats
            from utils.trade.analysis import save_summary_analysis
            from utils.notifier import send_summary_report
            from ai.analyzer import analyze_summary_stats

            summary_sent_cycle[cycle_key] = current_day if hours == 24 else current_hour
            _save_summary_sent_cycle(summary_sent_cycle)

            stats = calc_period_stats(hours)
            ai_analysis = None
            if stats and stats.get("total_trades", 0) > 0:
                ai_analysis = analyze_summary_stats(stats)
                save_summary_analysis(label, stats, ai_analysis)

            send_summary_report(label, stats, ai_analysis=ai_analysis)
            if stats:
                print(f"\n[汇总] {label} 报表已发送 (总盈亏: {stats['total_pnl']:+.2f} USDT)")
            else:
                print(f"\n[汇总] {label} 报表已发送 (无交易记录)")
        except Exception as e:
            print(f"\n[错误] {label} 汇总发送异常: {e}")
            import traceback
            traceback.print_exc()


def summary_loop():
    while True:
        try:
            _check_and_send_summary()
        except Exception as e:
            print(f"\n[错误] 汇总循环异常: {e}")
        time.sleep(60)
