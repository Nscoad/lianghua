"""
全场币种监控 — 每小时异常涨幅预警 + 每2分钟快速捞钱监测（做多/做空）
"""
import sqlite3
import os
import time
from datetime import datetime, timedelta
from core.trader import client
from utils.notifier import send_notification

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "market_monitor.db")
os.makedirs(DATA_DIR, exist_ok=True)

SURGE_THRESHOLD = 0.50
CHECK_INTERVAL = 3600
MIN_VOLUME_USDT = 1_000_000

# 快捞参数
FAST_CHECK_INTERVAL = 120    # 每2分钟检查一次
FAST_LOOKBACK = 900          # 对比15分钟前的价格
FAST_SURGE_THRESHOLD = 0.06  # 15分钟内涨幅>6%触发
FAST_MIN_VOLUME = 500_000    # 最低成交额

def _init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            symbol TEXT,
            price REAL,
            volume REAL,
            snapshot_time INTEGER,
            PRIMARY KEY (symbol, snapshot_time)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshot_time ON price_snapshots(snapshot_time)
    """)
    conn.commit()
    return conn

def get_all_usdt_symbols() -> list[dict]:
    """获取所有USDT永续合约的当前价格和24h成交额"""
    try:
        resp = client.rest_api.ticker24hr_price_change_statistics()
        d = resp.data()
        items = d.actual_instance
        results = []
        for t in items:
            sym = t.symbol
            if "_" in sym or not sym.endswith("USDT"):
                continue
            price = float(t.last_price or 0)
            volume = float(t.quote_volume or 0)
            if price > 0 and volume >= MIN_VOLUME_USDT:
                results.append({"symbol": sym, "price": price, "volume": volume})
        return results
    except Exception as e:
        print(f"[市场监控] 获取所有币种失败: {e}")
        return []

def _get_previous_snapshot(conn, symbol: str, cutoff: int) -> float | None:
    cursor = conn.execute(
        "SELECT price FROM price_snapshots WHERE symbol = ? AND snapshot_time >= ? ORDER BY snapshot_time ASC LIMIT 1",
        (symbol, cutoff)
    )
    row = cursor.fetchone()
    return row[0] if row else None

def _save_snapshot(conn, symbol: str, price: float, volume: float, now: int):
    conn.execute(
        "INSERT OR REPLACE INTO price_snapshots VALUES (?, ?, ?, ?)",
        (symbol, price, volume, now)
    )

def _cleanup_old_snapshots(conn, cutoff: int):
    conn.execute("DELETE FROM price_snapshots WHERE snapshot_time < ?", (cutoff,))

def run_market_monitor():
    """执行一轮全场监控：获取所有币种价格，与1小时前对比，发现异常涨幅则通知"""
    conn = _init_db()
    now = int(time.time())
    one_hour_ago = now - CHECK_INTERVAL
    two_hours_ago = now - CHECK_INTERVAL * 2

    symbols = get_all_usdt_symbols()
    if not symbols:
        conn.close()
        return

    surges = []
    for s in symbols:
        sym = s["symbol"]
        price = s["price"]
        volume = s["volume"]

        _save_snapshot(conn, sym, price, volume, now)

        prev_price = _get_previous_snapshot(conn, sym, one_hour_ago)
        if prev_price and prev_price > 0:
            change = (price - prev_price) / prev_price
            if change >= SURGE_THRESHOLD:
                surges.append({
                    "symbol": sym,
                    "price": price,
                    "prev_price": prev_price,
                    "change": change,
                    "volume": volume,
                })

    conn.commit()
    _cleanup_old_snapshots(conn, two_hours_ago)
    conn.close()

    if surges:
        surges.sort(key=lambda x: x["change"], reverse=True)
        lines = ["<h3>异常涨幅预警</h3>"]
        lines.append(f"检测时间: {datetime.now().strftime('%H:%M:%S')}<br>")
        lines.append("<hr>")
        for s in surges[:10]:
            lines.append(f"<b>{s['symbol']}</b> 涨幅: +{s['change']*100:.1f}%<br>")

        try:
            from utils.market_cap import get_top_gainers
            gainers = get_top_gainers(5)
            if gainers:
                lines.append("<hr><b>CoinMarketCap 1h涨幅榜</b><br>")
                for g in gainers:
                    lines.append(f"#{g['rank']} {g['symbol']}: +{g['percent_change_1h']:.2f}% (24h:{g['percent_change_24h']:+.2f}%)<br>")
        except Exception:
            pass

        content = "\n".join(lines)
        send_notification(f"异常涨幅 {len(surges)}个币种 (最高+{surges[0]['change']*100:.1f}%)", content)
        print(f"[市场监控] 检测到 {len(surges)} 个异常涨幅币种，已推送微信")
    else:
        print(f"[市场监控] 本轮无异常涨幅 (监控 {len(symbols)} 个币种)")


def run_fast_monitor():
    """每2分钟监测：检测快速涨幅并触发快捞"""
    from utils.fast_trader import check_fast_position, try_fast_open, try_fast_short

    check_fast_position()

    conn = _init_db()
    now = int(time.time())
    lookback_ago = now - FAST_LOOKBACK  # 对比15分钟前

    symbols = get_all_usdt_symbols()
    if not symbols:
        conn.close()
        return

    triggered = []
    for s in symbols:
        sym = s["symbol"]
        price = s["price"]
        volume = s["volume"]

        _save_snapshot(conn, sym, price, volume, now)

        prev_price = _get_previous_snapshot(conn, sym, lookback_ago)
        if prev_price and prev_price > 0 and volume >= FAST_MIN_VOLUME:
            change = (price - prev_price) / prev_price
            if change >= FAST_SURGE_THRESHOLD:
                # 涨 → 做多（情绪币追涨）
                triggered.append({"symbol": sym, "change": change, "price": price, "prev_price": prev_price})
                try_fast_open(sym, price, prev_price)
            elif change <= -FAST_SURGE_THRESHOLD:
                # 跌 → 做空（恐慌盘跟跌）
                triggered.append({"symbol": sym, "change": change, "price": price, "prev_price": prev_price})
                try_fast_short(sym, price, prev_price)

    conn.commit()
    conn.close()

    if triggered:
        print(f"[快捞] 监测 {len(symbols)} 币种，{len(triggered)} 个触发条件")
        for t in triggered[:5]:
            direction = "+" if t['change'] >= 0 else ""
            print(f"  {t['symbol']}: {direction}{t['change']*100:.1f}%")
