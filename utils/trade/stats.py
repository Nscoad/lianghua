"""交易统计 — 基于 DB 查询"""
import os
from datetime import datetime
from utils.db import calc_period_stats as db_calc_period_stats, get_trade_records as db_get_trades

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


def reconcile_trades():
    """
    系统启动时调用：从交易所拉取历史成交，补漏 trade_records 表中缺失的记录。
    仅补录最近 3 天的开平仓记录，避免重复。
    """
    from core.client import client
    from datetime import timedelta

    since = datetime.now() - timedelta(days=3)
    since_ts = int(since.timestamp())  # 硬编码7月22号凌晨3点

    # 获取启动时已存在的订单ID
    existing = db_get_trades(99999)
    existing_ids = set()
    for r in existing:
        oid = r.get("order_id")
        if oid:
            existing_ids.add(oid)

    try:
        trades = client.rest_api.account_trade_list(
            symbol="BTCUSDT",
            limit=100,
            start_time=since_ts * 1000,
        )
        data = trades.data()
        items = data.actual_instance
        for t in items:
            if t.order_id in existing_ids:
                continue
            sym = t.symbol
            side = "BUY" if t.is_buyer else "SELL"
            # BUY开多/SELL平多；SELL开空/BUY平空
            if side == "BUY":
                trade_side = "LONG"
            else:
                trade_side = "SHORT"
            is_close = t.realized_pnl is not None and float(t.realized_pnl) != 0
            if not is_close:
                continue
            # 该订单已平仓记录，补录
            from utils.db import insert_trade_record
            record = {
                "time": datetime.fromtimestamp(t.time / 1000).isoformat(),
                "symbol": sym, "side": trade_side,
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
            print(f"[对账] 补录 {sym} {trade_side} 盈亏{record['net_pnl']:+.2f}")
    except Exception as e:
        print(f"[对账] 拉取交易所历史成交失败: {e}")
