"""交易统计 — 基于 DB 查询"""
import os
from datetime import datetime
from utils.db import calc_period_stats as db_calc_period_stats, get_trade_records as db_get_trades
from utils.state import load_fast_state

STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "trade_stats.json")


def calc_period_stats(hours: int) -> dict | None:
    return db_calc_period_stats(hours)


def calc_6h_stats() -> dict | None:
    return db_calc_period_stats(6)


def print_summary():
    records = db_get_trades(99999)
    if not records:
        print("暂无交易记录")
        return
    total = len(records)
    pnl = sum(r.get("net_pnl", 0) for r in records)
    wins = sum(1 for r in records if r.get("net_pnl", 0) > 0)
    rate = wins / total * 100
    first = records[-1].get("time", "?")[:19]
    last = records[0].get("time", "?")[:19]
    print(f"汇总（{first} ~ {last}）: {total} 笔交易, 盈亏 {pnl:+.2f}, 胜率 {rate:.1f}%")


def _extract_trade_items(trades_response) -> list:
    """统一处理 account_trade_list 返回格式（实际实例 vs 列表）"""
    data = trades_response.data()
    if hasattr(data, "actual_instance"):
        raw = data.actual_instance
    else:
        raw = data
    if isinstance(raw, list):
        return raw
    if hasattr(raw, "actual_instance"):
        return raw.actual_instance
    return list(raw) if raw else []


def reconcile_trades(since: int | None = None):
    """
    系统启动时调用：从交易所拉取历史成交，补漏 trade_records 表中缺失的记录。
      - 收集所有交易过的币种（从 trade_records + 状态文件）
      - 对每个币种拉 account_trade_list
      - 按 order_id 去重，幂等补录
    可传入 since（Unix秒）指定拉取的起始时间，默认最近3天。
    """
    from core.client import client
    from datetime import timedelta

    if since is None:
        since_dt = datetime.now() - timedelta(days=3)
    else:
        since_dt = datetime.fromtimestamp(since)
    since_ts = int(since_dt.timestamp())

    # 1. 收集所有交易过的币种
    existing = db_get_trades(99999)
    symbols = set()
    for r in existing:
        sym = r.get("symbol", "").strip()
        if sym:
            symbols.add(sym)

    # 从状态文件补充（可能已有持仓但 DB 无记录）
    try:
        state = load_fast_state()
        for sym in state.get("positions", {}):
            if sym:
                symbols.add(sym)
    except Exception:
        pass

    if not symbols:
        symbols = {"BTCUSDT"}

    # 2. 获取已存在的订单 ID
    existing_ids = set()
    for r in existing:
        oid = r.get("order_id")
        if oid:
            existing_ids.add(oid)

    # 3. 逐币种拉取历史成交
    end_ts = int(datetime.now().timestamp() * 1000)
    from utils.db import insert_trade_record
    total_filled = 0

    for symbol in sorted(symbols):
        try:
            trades = client.rest_api.account_trade_list(
                symbol=symbol,
                limit=500,
                start_time=since_ts * 1000,
                end_time=end_ts,
            )
            items = _extract_trade_items(trades)
        except Exception as e:
            print(f"[对账] {symbol} 拉取失败（跳过）: {e}")
            continue

        for t in items:
            if t.order_id in existing_ids:
                continue
            is_close = t.realized_pnl is not None and float(t.realized_pnl) != 0
            if not is_close:
                continue

            trade_side = "LONG" if t.buyer else "SHORT"
            record = {
                "time": datetime.fromtimestamp(t.time / 1000).isoformat(),
                "symbol": symbol,
                "side": trade_side,
                "reason": "补录",
                "realized_pnl": round(float(t.realized_pnl), 2),
                "fee": round(abs(float(t.commission)), 4),
                "net_pnl": round(float(t.realized_pnl) - abs(float(t.commission)), 2),
                "qty": abs(float(t.qty)),
                "entry_price": round(float(t.price), 8),
                "exit_price": round(float(t.price), 8),
                "is_partial": False,
                "order_id": t.order_id,
            }
            insert_trade_record(record)
            existing_ids.add(t.order_id)
            total_filled += 1
            print(f"[对账] 补录 {symbol} {trade_side} 盈亏{record['net_pnl']:+.2f}")

    print(f"[对账] 完成：扫描 {len(symbols)} 个币种，补录 {total_filled} 条")


def periodic_reconcile(hours: int = 1):
    """
    轻量级定时对账：扫描最近 N 小时的所有币种成交记录，补漏缺失记录。
    由 scheduler 每30分钟调用一次，确保流水完整性。
    相比 reconcile_trades 更轻量（不读状态文件，不查过远历史）。
    """
    from core.client import client
    from datetime import timedelta
    from utils.db import insert_trade_record

    since_ts = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)

    # 1. 获取已有记录的所有币种
    existing = db_get_trades(99999)
    symbols = set()
    existing_ids = set()
    for r in existing:
        sym = r.get("symbol", "").strip()
        if sym:
            symbols.add(sym)
        oid = r.get("order_id")
        if oid:
            existing_ids.add(oid)

    if not symbols:
        return

    total_filled = 0
    for symbol in sorted(symbols):
        try:
            trades = client.rest_api.account_trade_list(
                symbol=symbol,
                limit=100,
                start_time=since_ts,
            )
            items = _extract_trade_items(trades)
        except Exception:
            continue

        for t in items:
            if t.order_id in existing_ids:
                continue
            is_close = t.realized_pnl is not None and float(t.realized_pnl) != 0
            if not is_close:
                continue

            trade_side = "LONG" if t.buyer else "SHORT"
            record = {
                "time": datetime.fromtimestamp(t.time / 1000).isoformat(),
                "symbol": symbol,
                "side": trade_side,
                "reason": "补充",
                "realized_pnl": round(float(t.realized_pnl), 2),
                "fee": round(abs(float(t.commission)), 4),
                "net_pnl": round(float(t.realized_pnl) - abs(float(t.commission)), 2),
                "qty": abs(float(t.qty)),
                "entry_price": round(float(t.price), 8),
                "exit_price": round(float(t.price), 8),
                "is_partial": False,
                "order_id": t.order_id,
            }
            insert_trade_record(record)
            existing_ids.add(t.order_id)
            total_filled += 1
            print(f"[对账] 补充 {symbol} {trade_side} 盈亏{record['net_pnl']:+.2f}")

    if total_filled > 0:
        print(f"[对账] 定时补充完成：扫描 {len(symbols)} 个币种，补充 {total_filled} 条")
