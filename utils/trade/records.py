"""交易流水记录 — 写 SQLite"""
from datetime import datetime
from utils.db import insert_trade_record


def record_close(symbol: str, reason: str, realized_pnl: float, qty: float,
                 entry_price: float, exit_price: float, side: str,
                 is_partial: bool = False, fee: float = 0.0, order_id: int = 0):
    record = {
        "time": datetime.now().isoformat(), "symbol": symbol, "side": side,
        "reason": reason, "realized_pnl": round(realized_pnl, 2),
        "fee": round(fee, 4), "net_pnl": round(realized_pnl - fee, 2),
        "qty": qty, "entry_price": round(entry_price, 8),
        "exit_price": round(exit_price, 8), "is_partial": is_partial,
    }
    if order_id:
        record["order_id"] = order_id
    insert_trade_record(record)
    tag = "盈利" if realized_pnl >= 0 else "亏损"
    fee_str = f" (手续费 {fee:.4f})" if fee > 0 else ""
    print(f"[交易流水] {symbol} {side} {tag} {realized_pnl:+.2f} USDT{fee_str}")


def record_open(symbol: str, side: str, qty: float, price: float,
                fee: float = 0.0, order_id: int = 0):
    record = {
        "time": datetime.now().isoformat(), "symbol": symbol, "side": side,
        "reason": "open", "realized_pnl": 0.0,
        "fee": round(fee, 4), "net_pnl": round(-fee, 2),
        "qty": qty, "entry_price": round(price, 8),
        "exit_price": 0.0, "is_partial": False,
    }
    if order_id:
        record["order_id"] = order_id
    insert_trade_record(record)
