"""
调度器 — 4个并行循环的启动入口

  持仓监控(5秒)  快捞监控(2分钟)  汇总报表(1h/3h/6h/12h/24h)  定时对账(30分钟)
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
        summary_loop, fast_loop, position_loop, reconcile_loop,
    )
    from scheduler.conditions import check_prerequisites, print_status

    init_db()
    patch_print()
    print("=" * 60)
    print("  币安 U本位合约 自动化交易系统")
    print("  持仓监控循环:    每 5 秒（检查快捞仓位止损/锁仓）")
    print("  快捞监测循环:    每 2 分钟（监测500+币种，涨7.3%触发追涨杀跌）")
    print("  定时对账循环:    每 30 分钟（扫描最近1小时补漏缺失记录）")
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

    # 核对状态文件 vs 交易所持仓，自动恢复误标 closed 的仓位
    try:
        from core.client import client
        from utils.state import load_fast_state, save_fast_state
        from utils.trade.fast_trader import _calc_kline_lock_floor, FAST_LEVERAGE

        state = load_fast_state()
        positions = state.get("positions", {})
        state_changed = False

        resp = client.rest_api.position_information_v3()
        for p in resp.data():
            amt = abs(float(p.position_amt))
            if amt <= 0:
                continue
            sym = p.symbol
            entry = float(p.entry_price or 0)
            mark = float(p.mark_price or 0)
            side = "LONG" if float(p.position_amt) > 0 else "SHORT"

            pos = positions.get(sym)
            if pos and not pos.get("closed", False):
                # 状态正常，跳过
                continue
            if entry <= 0 or amt <= 0:
                continue

            # 计算当前盈亏
            pnl_ratio = (mark - entry) / entry if side == "LONG" else (entry - mark) / entry
            pnl_ratio *= FAST_LEVERAGE

            if pos:
                # 恢复误标 closed 的仓位
                print(f"[状态对账] {sym} 交易所仍有持仓，恢复状态 (closed → active)")
                pos["closed"] = False
                pos["side"] = side
                pos["entry_price"] = entry
                pos["qty"] = amt
                if pnl_ratio > pos.get("highest_profit_pct", 0):
                    pos["highest_profit_pct"] = pnl_ratio
                floor = _calc_kline_lock_floor(sym, pos["highest_profit_pct"])
                pos["profit_floor"] = floor if floor else 0
            else:
                # 新建状态（交易所的持仓在状态文件中不存在，可能是手动开的）
                print(f"[状态对账] {sym} 交易所持仓在状态文件中不存在，新建条目")
                hp = max(pnl_ratio, 0)
                floor = _calc_kline_lock_floor(sym, hp)
                positions[sym] = {
                    "side": side, "entry_price": entry, "qty": amt,
                    "margin": 0, "open_time": "",
                    "closed": False, "highest_profit_pct": hp,
                    "profit_floor": floor if floor else 0,
                }
            state_changed = True

        if state_changed:
            save_fast_state(state)
            print("[状态对账] 完成")
    except Exception as e:
        print(f"[状态对账] 异常: {e}")

    threads = [
        threading.Thread(target=position_loop, daemon=True, name="Position-Monitor"),
        threading.Thread(target=fast_loop, daemon=True, name="Fast-Trade"),
        threading.Thread(target=reconcile_loop, daemon=True, name="Reconcile-Trades"),
        threading.Thread(target=summary_loop, daemon=True, name="Summary-Report"),
    ]
    for t in threads:
        t.start()

    print("\n四个循环已启动，按 Ctrl+C 停止。\n")
    time.sleep(1)
    print_status()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[停止] 收到中断信号，系统停止。")
        flush_log()
