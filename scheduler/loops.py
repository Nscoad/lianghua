"""5个并行循环线程"""
import time
from datetime import datetime
from collector.trend_collector import collect_trends
from strategy.risk_monitor import check_risk_once
from utils.market_monitor import run_market_monitor, run_fast_monitor
from scheduler.state import (
    risk_count, last_status,
    summary_sent_cycle, _save_summary_sent_cycle,
)
from scheduler import RISK_INTERVAL, MONITOR_INTERVAL, FAST_MONITOR_INTERVAL


# ==================== 风险监控循环（1.5秒） ====================

def run_risk_check():
    global risk_count, last_status
    risk_count += 1
    status = check_risk_once(silent=True)
    if status != last_status:
        t = datetime.now().strftime("%H:%M:%S")
        if status == "holding" and last_status == "no_position":
            print("\n[风险监控] 检测到新持仓，监控已启动")
        elif status != "no_position":
            print(f"\n[风险监控] {t} — {status}")
        elif last_status not in ("no_position", "") and status == "no_position":
            print(f"\n[风险监控] {t} — 持仓已清")
        last_status = status
    return status


def risk_loop():
    while True:
        try:
            run_risk_check()
        except Exception as e:
            print(f"\n[错误] 风险监控异常: {e}")
        time.sleep(RISK_INTERVAL if last_status != "no_position" else 30)


# ==================== 汇总报表循环（每分钟） ====================

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
            from utils.trade_stats import calc_period_stats
            from utils.trade_analysis import save_summary_analysis
            from utils.notifier import send_summary_report
            from ai.analyzer import analyze_summary_stats
            from utils.trader_orch import decide_data_source, save_review, should_switch_strategy

            summary_sent_cycle[cycle_key] = current_day if hours == 24 else current_hour
            _save_summary_sent_cycle(summary_sent_cycle)

            # 本轮数据源决策
            decision = decide_data_source()
            print(f"  [决策] 数据源: {decision['reason']}")

            stats = calc_period_stats(hours)
            ai_analysis = None
            if stats and stats.get("total_trades", 0) > 0:
                ai_analysis = analyze_summary_stats(stats)
                save_summary_analysis(label, stats, ai_analysis)

            # 复盘写入 JSON
            save_review(label, stats, ai_analysis=ai_analysis, decision=decision)

            send_summary_report(label, stats, ai_analysis=ai_analysis)
            if stats:
                print(f"\n[汇总] {label} 报表已发送 (总盈亏: {stats['total_pnl']:+.2f} USDT)")
                # 自适应检查
                sw = should_switch_strategy()
                if sw.get("switch"):
                    print(f"  [自适应] {sw['reason']}")
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


# ==================== 全场监控循环（1小时） ====================

def monitor_loop():
    while True:
        try:
            run_market_monitor()
        except Exception as e:
            print(f"\n[错误] 市场监控循环异常: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(MONITOR_INTERVAL)


# ==================== 快速捞钱循环（2分钟） ====================

def fast_loop():
    """每2分钟监测全场币种，涨幅>3%触发快捞"""
    while True:
        try:
            run_fast_monitor()
        except Exception as e:
            print(f"\n[错误] 快捞循环异常: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(FAST_MONITOR_INTERVAL)


# ==================== 趋势采集循环（15分钟） ====================

TREND_INTERVAL = 15 * 60  # 15分钟

_trend_lock = False


def trend_loop():
    """每15分钟采集广场热门 + X.com 趋势数据，供候选币分析使用"""
    global _trend_lock
    print("[趋势采集] 线程已启动，等待首次采集...")
    time.sleep(30)  # 启动后等30秒再开始，让系统先稳定
    while True:
        if _trend_lock:
            time.sleep(10)
            continue
        _trend_lock = True
        try:
            collect_trends(max_items_per_source=10)
        except Exception as e:
            print(f"\n[错误] 趋势采集循环异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            _trend_lock = False
        time.sleep(TREND_INTERVAL)
