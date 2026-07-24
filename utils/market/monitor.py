"""
全场币种监控 — 每30分钟全市场概况+AI分析 + 每1分钟快速捞钱监测（做多/做空）
"""
import json
import sqlite3
import os
import time
from datetime import datetime
from core.client import client
from utils.trade.fast_trader import check_fast_position, try_fast_open, try_fast_short

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
DB_PATH = os.path.join(DATA_DIR, "market_monitor.db")
os.makedirs(DATA_DIR, exist_ok=True)

CHECK_INTERVAL = 1800         # 30分钟
MIN_VOLUME_USDT = 1_000_000

# 快捞参数
FAST_CHECK_INTERVAL = 60     # 每1分钟检查一次
FAST_LOOKBACK = 900          # 对比15分钟前的价格
FAST_SURGE_THRESHOLD = 0.073  # 15分钟内涨跌幅度 >7.3% 触发
FAST_MIN_VOLUME = 500_000    # 最低成交额

def _init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
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
    """执行一轮全场监控：30分钟间隔，采集全市场涨跌概况 + AI分析"""
    conn = _init_db()
    now = int(time.time())
    lookback = now - CHECK_INTERVAL  # 对比30分钟前
    cleanup = now - CHECK_INTERVAL * 2

    symbols = get_all_usdt_symbols()
    if not symbols:
        conn.close()
        return

    # 采集快照并计算涨跌
    movers = []
    for s in symbols:
        sym = s["symbol"]
        price = s["price"]
        volume = s["volume"]

        _save_snapshot(conn, sym, price, volume, now)
        conn.commit()

        prev_price = _get_previous_snapshot(conn, sym, lookback)
        if prev_price and prev_price > 0:
            change = (price - prev_price) / prev_price
            movers.append({
                "symbol": sym, "change": round(change, 4),
                "price": price, "volume": volume,
            })

    _cleanup_old_snapshots(conn, cleanup)
    conn.close()

    # 排序：涨幅榜 + 跌幅榜
    movers.sort(key=lambda x: x["change"], reverse=True)
    top_gainers = [m for m in movers if m["change"] > 0][:5]
    top_losers = [m for m in movers if m["change"] < 0][-5:]
    top_losers.reverse()

    # 汇总涨跌统计
    up_count = sum(1 for m in movers if m["change"] > 0)
    down_count = sum(1 for m in movers if m["change"] < 0)
    avg_change = sum(m["change"] for m in movers) / len(movers) if movers else 0

    # 构建市场概况描述文本
    summary = _build_market_summary(movers, top_gainers, top_losers, up_count, down_count, avg_change)

    # AI分析
    ai_result = _ai_analyze_market(top_gainers, top_losers, up_count, down_count, avg_change)

    # 保存到JSON，供看板读取
    report = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_symbols": len(symbols),
        "up_count": up_count,
        "down_count": down_count,
        "avg_change": round(avg_change * 100, 2),
        "top_gainers": [{"symbol": m["symbol"], "change": round(m["change"] * 100, 1), "price": m["price"]} for m in top_gainers],
        "top_losers": [{"symbol": m["symbol"], "change": round(m["change"] * 100, 1), "price": m["price"]} for m in top_losers],
        "summary": summary,
        "ai_analysis": ai_result,
    }
    _save_analysis(report)

    # 打印到控制台
    print(f"\n[市场概况] {datetime.now().strftime('%H:%M')} 涨{up_count}/跌{down_count} 均{avg_change*100:+.2f}%")
    gainers_str = ", ".join(f"{m['symbol']}+{m['change']*100:.1f}%" for m in top_gainers)
    losers_str = ", ".join(f"{m['symbol']}{m['change']*100:.1f}%" for m in top_losers)
    print(f"  涨幅前5: {gainers_str}")
    print(f"  跌幅前5: {losers_str}")
    if ai_result:
        print(f"  [AI分析] {ai_result['summary']}")


def _build_market_summary(movers, top_gainers, top_losers, up_count, down_count, avg_change) -> str:
    """构建自然语言的市场概况描述"""
    parts = []
    total = len(movers)
    if total == 0:
        return "暂无数据"

    ratio = up_count / down_count if down_count > 0 else float("inf")

    if ratio > 2:
        parts.append(f"市场整体偏多，{up_count}涨/{down_count}跌，多头占优")
    elif ratio < 0.5:
        parts.append(f"市场整体偏空，{up_count}涨/{down_count}跌，空头占优")
    else:
        parts.append(f"市场震荡，{up_count}涨/{down_count}跌，多空均衡")

    parts.append(f"平均涨跌{avg_change*100:+.2f}%")

    if top_gainers:
        g = top_gainers[0]
        parts.append(f"最强 {g['symbol']}+{g['change']*100:.1f}%")
    if top_losers:
        loser = top_losers[0]
        parts.append(f"最弱 {loser['symbol']}{loser['change']*100:.1f}%")

    return "，".join(parts)


def _ai_analyze_market(top_gainers, top_losers, up_count, down_count, avg_change) -> dict | None:
    """调用AI分析当前市场状态"""
    try:
        from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL
        if not DEEPSEEK_API_KEY:
            return None
    except Exception:
        return None

    # 构建市场上下文
    gainers_text = "\n".join(f"+{m['change']*100:.1f}% {m['symbol']} (${m['price']})" for m in top_gainers[:5])
    losers_text = "\n".join(f"{m['change']*100:.1f}% {m['symbol']} (${m['price']})" for m in top_losers[:5])

    prompt = f"""当前市场概况（30分钟涨跌幅）：
涨{up_count}个 / 跌{down_count}个 / 均值{avg_change*100:+.2f}%

涨幅前5：
{gainers_text}

跌幅前5：
{losers_text}

请分析：
1. 当前市场情绪（看多/看空/震荡）
2. 是否存在明显的板块效应（涨幅集中的同类币种）
3. 对短线交易的建议（一句话）
输出JSON格式：{{"sentiment":"看多/看空/震荡","summary":"一句话市场判断","advice":"短线建议"}}"""

    try:
        import requests
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=15,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # 提取JSON
        import re
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            result = json.loads(m.group())
            return result
        return {"sentiment": "震荡", "summary": content[:100], "advice": ""}
    except Exception as e:
        print(f"  [AI分析] DeepSeek调用失败: {e}")
        return None


def _save_analysis(report: dict):
    """保存市场分析报告到JSON文件"""
    fp = os.path.join(DATA_DIR, "market_analysis.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def run_fast_monitor():
    """每1分钟监测：检测快速涨幅并触发快捞"""
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
        conn.commit()  # 每条快照单独提交，避免长事务阻塞其他线程

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
    conn.close()

    if triggered:
        print(f"[快捞] 监测 {len(symbols)} 币种，{len(triggered)} 个触发条件")
        for t in triggered[:5]:
            direction = "+" if t['change'] >= 0 else ""
            print(f"  {t['symbol']}: {direction}{t['change']*100:.1f}%")
