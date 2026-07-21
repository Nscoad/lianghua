"""
CoinMarketCap API — 获取全市场币种排名、价格、涨幅数据
"""
import json
import os
import time
import requests

from config import CMC_API_KEY, CMC_API_URL as CMC_URL

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CACHE_FILE = os.path.join(DATA_DIR, "cmc_cache.json")
CACHE_TTL = 900  # 15分钟缓存


def fetch_top_coins(limit: int = 50, convert: str = "USDT") -> list[dict]:
    """获取CoinMarketCap排名前N的币种数据"""
    cache = _load_cache()
    if cache and time.time() - cache.get("time", 0) < CACHE_TTL:
        return cache.get("data", [])

    try:
        resp = requests.get(
            CMC_URL,
            headers={"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"},
            params={"limit": limit, "convert": convert},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[CMC] API 错误: {resp.status_code} {resp.text[:200]}")
            return cache.get("data", []) if cache else []

        data = resp.json().get("data", [])
        result = []
        for coin in data:
            quote = coin.get("quote", {}).get(convert, {})
            result.append({
                "rank": coin.get("cmc_rank", 0),
                "symbol": coin.get("symbol", "") + "USDT",
                "name": coin.get("name", ""),
                "price": quote.get("price", 0),
                "volume_24h": quote.get("volume_24h", 0),
                "percent_change_1h": quote.get("percent_change_1h", 0),
                "percent_change_24h": quote.get("percent_change_24h", 0),
                "percent_change_7d": quote.get("percent_change_7d", 0),
                "market_cap": quote.get("market_cap", 0),
                "updated": time.time(),
            })
        _save_cache(result)
        print(f"[CMC] 获取 {len(result)} 个币种数据 (排名前{limit})")
        return result
    except Exception as e:
        print(f"[CMC] 请求异常: {e}")
        return cache.get("data", []) if cache else []


def _load_cache() -> dict | None:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _save_cache(data: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"time": time.time(), "data": data}, f, ensure_ascii=False)


def get_top_gainers(limit: int = 10) -> list[dict]:
    """获取1小时涨幅最大的币种"""
    coins = fetch_top_coins(limit=100)
    coins.sort(key=lambda x: x.get("percent_change_1h", 0), reverse=True)
    return coins[:limit]


def format_market_summary(top_n: int = 10) -> str:
    """格式化市场概况文本（供AI prompt使用）"""
    coins = fetch_top_coins(limit=top_n)
    if not coins:
        return "[CMC] 暂无数据"

    lines = ["===== CoinMarketCap Top 10 ====="]
    for c in coins:
        lines.append(
            f"  #{c['rank']} {c['symbol']:<12} "
            f"${c['price']:<12.8f} "
            f"1h:{c['percent_change_1h']:+.2f}% "
            f"24h:{c['percent_change_24h']:+.2f}% "
            f"7d:{c['percent_change_7d']:+.2f}%"
        )
    return "\n".join(lines)
