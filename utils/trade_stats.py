"""交易统计 — 基于 DB 查询"""
import json
import os
from datetime import datetime
from utils.db import calc_period_stats as db_calc_period_stats, get_trade_records as db_get_trades

STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trade_stats.json")


def calc_period_stats(hours: int) -> dict | None:
    return db_calc_period_stats(hours)


def calc_6h_stats() -> dict | None:
    return db_calc_period_stats(6)


def print_summary():
    records = db_get_trades(99999)
    if not records:
        print("暂无交易记录")
        return
    total_pnl = win = loss = 0
    stats = {}
    for r in records:
        pnl = r.get("net_pnl", r.get("realized_pnl", 0))
        if r["reason"] == "open":
            continue
        total_pnl += pnl
        if pnl > 0: win += 1
        else: loss += 1
        sym = r["symbol"]
        if sym not in stats:
            stats[sym] = {"win": 0, "loss": 0, "pnl": 0}
        stats[sym]["pnl"] += pnl
        if pnl > 0: stats[sym]["win"] += 1
        else: stats[sym]["loss"] += 1

    trade_count = win + loss
    wr = win / trade_count * 100 if trade_count > 0 else 0
    print(f"\n{'='*50}")
    print(f"  交易流水汇总 ({trade_count}条)")
    print(f"{'='*50}")
    print(f"  净盈亏: {total_pnl:+.2f} USDT")
    print(f"  胜率:   {win}胜/{loss}败 ({wr:.1f}%)")
    print("  币种明细:")
    for sym, s in sorted(stats.items(), key=lambda x: x[1]["pnl"]):
        t = s["win"] + s["loss"]
        tag = "+" if s["pnl"] > 0 else "-"
        print(f"    {tag} {sym:<10} {s['pnl']:+.2f} USDT ({s['win']}胜/{s['loss']}败/{t}次)")
    print("=" * 50)


def save_6h_stats():
    stats = calc_6h_stats()
    if stats is None:
        print("[6h统计] 近6小时无平仓记录")
        return
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n{'='*50}")
    print(f"  [6h统计] {datetime.now().strftime('%H:%M')} — 近6小时交易回顾")
    print(f"{'='*50}")
    print(f"  总平仓: {stats['total_trades']}笔 | 净盈亏: {stats['total_pnl']:+.2f} USDT")
    print(f"  胜率:   {stats['win']}胜/{stats['loss']}败 ({stats['win_rate']}%)")


def get_stats() -> dict | None:
    if not os.path.exists(STATS_FILE):
        return None
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def reconcile_trades(symbols: list[str] | None = None, since: float | None = None):
    """
    对账：从交易所补录本地缺失的成交。

    since: 时间戳（秒），只补录此时间之后的成交。传 None 则补录全部。
    """
    try:
        from core.trader import client
        from datetime import datetime as dt
        from utils.db import get_trade_records as db_get, insert_trade_record as db_insert

        if since:
            print(f"  [对账] 只补录 {dt.fromtimestamp(since).strftime('%Y-%m-%d %H:%M:%S')} 之后的成交")

        if symbols is None:
            from utils.market_screener import get_dynamic_candidates
            symbols = get_dynamic_candidates(top_n=5) or ["BANKUSDT"]

        local_order_ids = set()
        local_records = db_get(99999)
        for r in local_records:
            if r.get("order_id"):
                local_order_ids.add(r["order_id"])

        backfilled = 0
        for symbol in symbols:
            try:
                resp = client.rest_api.account_trade_list(symbol=symbol, limit=100)
                fills = resp.data()
            except Exception:
                continue

            orders = {}
            for f in fills:
                oid = f.order_id
                if oid not in orders:
                    orders[oid] = {"qty": 0, "pnl": 0, "fee": 0, "price": 0, "side": f.side, "time": f.time}
                qty = float(f.qty or 0)
                orders[oid]["qty"] += qty
                orders[oid]["pnl"] += float(f.realized_pnl or 0)
                orders[oid]["fee"] += float(f.commission or 0) if f.commission_asset == "USDT" else 0
                orders[oid]["price"] = float(f.price or 0)

            for oid, o in orders.items():
                if oid in local_order_ids:
                    continue
                # 过滤：只补录 since 之后的数据
                if since and (o["time"] / 1000) < since:
                    continue
                already = False
                ts_oid = dt.fromtimestamp(o["time"] / 1000)
                for r in local_records:
                    if r["symbol"] != symbol:
                        continue
                    if abs((dt.fromisoformat(r["time"]) - ts_oid).total_seconds()) > 60:
                        continue
                    if abs(r["qty"] - o["qty"]) / max(r["qty"], o["qty"], 1) > 0.1:
                        continue
                    already = True
                    break
                if already:
                    continue

                ts_str = ts_oid.strftime('%H:%M:%S')
                is_buy = o["side"] == "BUY"
                if round(o["pnl"], 2) == 0:
                    record = {"time": ts_oid.isoformat(), "symbol": symbol,
                              "side": "LONG" if is_buy else "SHORT", "reason": "open",
                              "realized_pnl": 0.0, "fee": round(o["fee"], 4),
                              "net_pnl": round(-o["fee"], 2), "qty": round(o["qty"]),
                              "entry_price": round(o["price"], 8), "exit_price": 0.0,
                              "is_partial": False, "order_id": oid}
                else:
                    record = {"time": ts_oid.isoformat(), "symbol": symbol,
                              "side": "SHORT" if is_buy else "LONG", "reason": "reconcile",
                              "realized_pnl": round(o["pnl"], 2), "fee": round(o["fee"], 4),
                              "net_pnl": round(o["pnl"] - o["fee"], 2), "qty": round(o["qty"]),
                              "entry_price": 0.0, "exit_price": round(o["price"], 8),
                              "is_partial": False, "order_id": oid}
                db_insert(record)
                local_order_ids.add(oid)
                backfilled += 1
                label = "开仓" if record["reason"] == "open" else "平仓"
                print(f"  [补记] {label} {symbol} order_id={oid} fee={record['fee']:.4f} @ {ts_str}")

        if backfilled:
            print(f"[对账] 补记了 {backfilled} 条缺失流水")
        else:
            print("[对账] 流水完整，无缺失")
    except Exception as e:
        print(f"[对账] 异常: {e}")
