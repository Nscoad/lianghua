"""5个并行循环线程：快捞、持仓监控、汇总报表、定时对账"""
import time
import traceback
from datetime import datetime
from utils.market.monitor import run_fast_monitor
from scheduler import FAST_MONITOR_INTERVAL
from scheduler.state import (
    summary_sent_cycle, _save_summary_sent_cycle,
)
from utils.state import beat
from utils.trade.fast_trader import check_fast_position
from utils.trade.stats import calc_period_stats, periodic_reconcile
from utils.trade.analysis import save_summary_analysis
from utils.notifier import send_summary_report
from ai.analyzer import analyze_summary_stats
from core.funding import check_and_record_funding


# ==================== 快捞循环（1分钟） ====================

def fast_loop():
    """每1分钟监测全场币种，涨幅>7.3%触发快捞"""
    while True:
        try:
            run_fast_monitor()
        except Exception as e:
            print(f"\n[错误] 快捞循环异常: {e}")
            traceback.print_exc()
        beat("fast_loop", "ok")
        time.sleep(FAST_MONITOR_INTERVAL)


# ==================== 持仓监控循环（5秒） ====================

def position_loop():
    """
    每5秒检查已有快捞持仓的止损/浮动锁仓。
    与 fast_loop 分离，避免1分钟间隔导致跳空止损。
    """
    print("[持仓监控] 线程已启动（每5秒检查止损/锁仓）")
    time.sleep(3)  # 启动后等3秒
    while True:
        try:
            check_fast_position()
        except Exception as e:
            print(f"\n[错误] 持仓监控异常: {e}")
            traceback.print_exc()
        beat("position_loop", "ok")
        time.sleep(5)


# ==================== 资金费率循环（10分钟） ====================

def funding_loop():
    """
    每10分钟检查一次所有持仓的资金费率流水。
    独立线程，不阻塞5秒持仓监控。
    """
    print("[资金费率] 线程已启动（每10分钟检查一次）")
    time.sleep(30)  # 启动后等30秒，避开启动高峰
    while True:
        try:
            total = check_and_record_funding()
            if total != 0:
                print(f"[资金费率] 本次新增资金费 {total:+.4f} USDT")
        except Exception as e:
            print(f"[资金费率] 检查异常: {e}")
        beat("funding_loop", "ok")
        time.sleep(600)  # 10分钟


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
            traceback.print_exc()


def summary_loop():
    while True:
        try:
            _check_and_send_summary()
        except Exception as e:
            print(f"\n[错误] 汇总循环异常: {e}")
        beat("summary_loop")
        time.sleep(60)


# ==================== 定时对账循环（30分钟） ====================

def reconcile_loop():
    """
    每30分钟扫描最近1小时的所有成交记录，补漏缺失的平仓流水。
    确保 trade_records 数据的完整性。
    """
    print("[定时对账] 线程已启动（每30分钟补充遗漏记录）")
    time.sleep(10)  # 等启动对账跑完
    while True:
        try:
            periodic_reconcile()
        except Exception as e:
            print(f"\n[错误] 定时对账异常: {e}")
        beat("reconcile_loop")
        time.sleep(1800)
