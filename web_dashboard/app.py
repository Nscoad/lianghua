"""本地看板后端 — 提供 API 供前端渲染"""
import json
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 Python 路径中 (sys.path.insert 必须在 flask import 之前)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

# 确保 static 目录存在
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ==================== 数据读取 ====================

def _get_db():
    db = DATA_DIR / "trading.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def _read_json(name: str) -> dict | list:
    fp = DATA_DIR / name
    if not fp.exists():
        return {}
    return json.loads(fp.read_text(encoding="utf-8"))


# ==================== API 接口 ====================

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        return ("ok", 200)
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/api/balance")
def api_balance():
    """账户余额（可用 + 钱包总余额）"""
    try:
        from core.client import client, _rate_limit
        _rate_limit()
        resp = client.rest_api.futures_account_balance_v3()
        available = 0.0
        wallet = 0.0
        for b in resp.data():
            if b.asset == "USDT":
                available = float(b.available_balance or 0)
                wallet = float(b.balance or 0)
                break
        return jsonify({
            "available": round(available, 2),
            "wallet": round(wallet, 2),
            "time": datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"available": 0, "wallet": 0, "error": str(e), "time": datetime.now().isoformat()})


@app.route("/api/position")
def api_position():
    """当前所有仓位（主仓 + 快捞多仓位）"""
    try:
        from core.client import client, _rate_limit
        _rate_limit()
        resp = client.rest_api.position_information_v3()

        positions = []
        for p in resp.data():
            amt = abs(float(p.position_amt))
            if amt <= 0:
                continue
            entry_price = float(p.entry_price or 0)
            mark_price = float(p.mark_price or 0)
            upnl = float(p.un_realized_profit or 0)
            side = "LONG" if float(p.position_amt) > 0 else "SHORT"
            positions.append({
                "symbol": p.symbol,
                "entry_price": entry_price,
                "mark_price": mark_price,
                "amount": amt,
                "unrealized_pnl": round(upnl, 2),
                "side": side,
            })

        # 合并快捞状态信息（锁仓线等）
        fast_state = _read_json("fast_trade_state.json")
        fast_positions = {}
        if isinstance(fast_state, dict):
            pos_dict = fast_state.get("positions", {})
            if not pos_dict and "symbol" in fast_state:
                # 旧格式迁移
                pos_dict = {fast_state["symbol"]: fast_state}
            for sym, data in pos_dict.items():
                if data.get("closed"):
                    continue
                fast_positions[sym] = {
                    "profit_floor": data.get("profit_floor", 0),
                    "highest_profit_pct": data.get("highest_profit_pct", 0),
                    "entry_price": data.get("entry_price", 0),
                }

        # 合并数据
        for pos in positions:
            sym = pos["symbol"]
            fp = fast_positions.get(sym, {})
            pos["profit_floor"] = fp.get("profit_floor", 0)
            pos["highest_profit_pct"] = fp.get("highest_profit_pct", 0)

        return jsonify({
            "has_position": len(positions) > 0,
            "positions": positions,
            "count": len(positions),
        })
    except Exception as e:
        return jsonify({"has_position": False, "positions": [], "error": str(e)})


@app.route("/api/logs")
def api_logs():
    """最近日志"""
    limit = int(os.environ.get("LOG_LIMIT", "200"))
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT time, message FROM run_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        logs = [{"time": r["time"], "message": r["message"]} for r in rows]
        logs.reverse()
        return jsonify({"logs": logs, "total": len(logs)})
    except Exception as e:
        return jsonify({"logs": [], "error": str(e)})


@app.route("/api/stats")
def api_stats():
    """周期统计 1h/3h/6h/12h/24h"""
    from utils.trade.stats import calc_period_stats
    periods = [1, 3, 6, 12, 24]
    result = {}
    for h in periods:
        try:
            stats = calc_period_stats(h)
            result[f"{h}h"] = stats
        except Exception as e:
            result[f"{h}h"] = {"error": str(e)}
    return jsonify(result)


@app.route("/api/summary")
def api_summary():
    """多空比 + 总览"""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM trade_records WHERE reason != 'open' AND realized_pnl != 0"
    ).fetchall()
    conn.close()
    total = len(rows)
    if total == 0:
        return jsonify({"total_trades": 0})

    long_pnl = short_pnl = 0.0
    long_count = short_count = 0
    total_pnl = 0.0
    win = 0
    for r in rows:
        pnl = r["net_pnl"] or r["realized_pnl"]
        total_pnl += pnl
        if pnl > 0:
            win += 1
        side = r["side"]
        if side == "LONG":
            long_count += 1
            long_pnl += pnl
        elif side == "SHORT":
            short_count += 1
            short_pnl += pnl

    return jsonify({
        "total_trades": total,
        "win": win,
        "loss": total - win,
        "win_rate": round(win / total * 100, 1) if total else 0,
        "total_pnl": round(total_pnl, 2),
        "long_count": long_count,
        "short_count": short_count,
        "long_short_ratio": round(long_count / short_count, 2) if short_count else (long_count if long_count else 1),
        "long_pnl": round(long_pnl, 2),
        "short_pnl": round(short_pnl, 2),
    })


@app.route("/api/signals")
def api_signals():
    """最近交易信号"""
    signals = _read_json("trade_signals.json")
    if isinstance(signals, list):
        signals = signals[-10:]
    return jsonify({"signals": signals if isinstance(signals, list) else []})


@app.route("/api/system")
def api_system():
    """系统运行时间等状态"""
    now = datetime.now()
    return jsonify({
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "data_dir": str(DATA_DIR),
    })


@app.route("/api/market_analysis")
def api_market_analysis():
    """30分钟市场概况 + AI分析"""
    analysis = _read_json("market_analysis.json")
    if not analysis:
        return jsonify({"available": False, "error": "暂无数据"})
    return jsonify({"available": True, **analysis})


def start_server(host="0.0.0.0", port=5000, debug=False):
    """启动看板服务器"""
    print(f"\n  📊 本地看板: http://localhost:{port}")
    print(f"  {'=' * 40}\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    start_server(debug=True)
