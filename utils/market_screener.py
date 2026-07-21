"""
市场筛选器 — 涨跌榜Top5 + K线阶段判断

情绪币特性：涨的容易继续涨，跌的容易继续跌。
功能：
  1. 从币安获取24小时涨跌榜前5
  2. 对每个币种做K线阶段分析（刚启动/中段/末端/横盘）
"""
import requests as _req
from config import get_futures_config

# 忽略成交量过低的币种（24h USDT成交量低于此值跳过）
MIN_VOLUME_USDT = 500_000


def _fetch_all_24hr_tickers() -> list[dict]:
    """获取所有U本位合约的24小时行情数据"""
    cfg = get_futures_config()
    try:
        resp = _req.get(
            f"{cfg['base_url']}/fapi/v1/ticker/24hr",
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def _is_tradable_usdt(symbol: str) -> bool:
    """是否为可交易的USDT合约（排除BUSD、UP/DOWN等特殊币种）"""
    if not symbol.endswith("USDT"):
        return False
    # 排除特殊后缀
    exclude_keywords = ["BUSD", "UP", "DOWN", "BEAR", "BULL"]
    for kw in exclude_keywords:
        if kw in symbol:
            return False
    return True


def fetch_top_movers(top_n: int = 5) -> dict:
    """
    获取涨跌榜TopN。

    Returns:
        {
            "gainers": [{"symbol":str, "change_pct":float, "volume":float, "price":float}, ...],
            "losers":  [{"symbol":str, "change_pct":float, "volume":float, "price":float}, ...],
        }
    """
    all_tickers = _fetch_all_24hr_tickers()
    if not all_tickers:
        return {"gainers": [], "losers": []}

    # 筛选USDT合约 + 成交量达标
    filtered = []
    for t in all_tickers:
        sym = t.get("symbol", "")
        if not _is_tradable_usdt(sym):
            continue
        vol_usdt = float(t.get("quoteVolume", 0))
        if vol_usdt < MIN_VOLUME_USDT:
            continue
        filtered.append({
            "symbol": sym,
            "change_pct": float(t.get("priceChangePercent", 0)),
            "volume": vol_usdt,
            "price": float(t.get("lastPrice", 0)),
        })

    # 按涨跌幅排序
    sorted_by_change = sorted(filtered, key=lambda x: x["change_pct"], reverse=True)

    gainers = sorted_by_change[:top_n]
    losers = sorted_by_change[-top_n:]
    losers.reverse()  # 跌幅最大的在前面

    return {"gainers": gainers, "losers": losers}


def _fetch_15m_klines(symbol: str, limit: int = 30) -> list:
    """获取15分钟K线"""
    cfg = get_futures_config()
    try:
        resp = _req.get(
            f"{cfg['base_url']}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "15m", "limit": limit},
            headers={"X-MBX-APIKEY": cfg["api_key"]},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def _calc_sma(values: list[float], period: int) -> float:
    """简单移动平均"""
    if len(values) < period:
        return values[-1] if values else 0
    return sum(values[-period:]) / period


def analyze_kline_stage(symbol: str, is_gainer: bool) -> dict:
    """
    K线阶段判断 — 判断该币种处于什么阶段。

    对情绪币的判断逻辑：
      - 涨跌幅大的币，看K线是否刚启动还是已经涨/跌了很久
      - 寻找"承接点"：价格回踩均线附近、放量止跌等

    Returns:
        {
            "stage": "just_started" | "mid_trend" | "extended" | "sideways" | "data_insufficient",
            "description": str,
            "current_price": float,
            "ma5": float,
            "ma20": float,
            "volume_ratio": float,
        }
    """
    klines = _fetch_15m_klines(symbol, limit=30)
    if len(klines) < 20:
        return {"stage": "data_insufficient", "description": f"{symbol} K线数据不足",
                "current_price": 0, "ma5": 0, "ma20": 0, "volume_ratio": 0}

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    current_price = closes[-1]

    ma5 = _calc_sma(closes, 5)
    ma20 = _calc_sma(closes, 20)

    # 成交量：最后一根 vs 近20根均量
    avg_vol_20 = sum(volumes[-20:]) / 20
    vol_ratio = volumes[-1] / avg_vol_20 if avg_vol_20 > 0 else 1

    # 价格相对均线位置
    price_vs_ma20 = (current_price - ma20) / ma20 * 100

    # 近10根涨幅
    change_10 = (closes[-1] - closes[-10]) / closes[-10] * 100 if closes[-10] > 0 else 0

    # 近20根涨幅（整体趋势）
    change_20 = (closes[-1] - closes[-20]) / closes[-20] * 100 if closes[-20] > 0 else 0

    # 判断阶段
    if is_gainer:
        # 涨幅榜
        if change_10 > 0 and change_20 > 0:
            # 整体在涨
            if change_10 > change_20 * 0.7:
                # 近10根涨幅占近20根的大部分 → 刚启动不久
                if vol_ratio > 1.3:
                    stage = "just_started"
                    desc = f"刚启动上涨，放量突破(近10根涨{change_10:.1f}%，量比{vol_ratio:.1f})"
                else:
                    stage = "mid_trend"
                    desc = f"上涨中段(近10根涨{change_10:.1f}%，量比{vol_ratio:.1f})"
            else:
                # 涨幅集中在更早的K线 → 已经涨了一段时间
                if price_vs_ma20 > 8:
                    stage = "extended"
                    desc = f"已涨较多，偏离MA20={price_vs_ma20:+.1f}%（近20根涨{change_20:.1f}%），追高风险大"
                else:
                    stage = "mid_trend"
                    desc = f"上涨中(近20根涨{change_20:.1f}%，偏离MA20={price_vs_ma20:+.1f}%)"
        elif change_10 < -2 and change_20 > 3:
            # 整体涨但近期回调 → 可能回踩支撑
            stage = "pullback"
            desc = f"涨后回踩(近10根跌{abs(change_10):.1f}%，近20根涨{change_20:.1f}%)，关注MA20支撑"
        else:
            stage = "sideways"
            desc = f"横盘震荡(近10根{change_10:+.1f}%，近20根{change_20:+.1f}%)"
    else:
        # 跌幅榜
        if change_10 < 0 and change_20 < 0:
            # 整体在跌
            if abs(change_10) > abs(change_20) * 0.7:
                # 近期跌幅占大部分 → 刚开始跌
                if vol_ratio > 1.3:
                    stage = "just_started"
                    desc = f"刚启动下跌，放量破位(近10根跌{abs(change_10):.1f}%，量比{vol_ratio:.1f})"
                else:
                    stage = "mid_trend"
                    desc = f"下跌中段(近10根跌{abs(change_10):.1f}%，量比{vol_ratio:.1f})"
            else:
                # 已经跌了很久
                if price_vs_ma20 < -8:
                    stage = "extended"
                    desc = f"已跌较深，偏离MA20={price_vs_ma20:+.1f}%，可能超跌反弹"
                else:
                    stage = "mid_trend"
                    desc = f"持续下跌(近20根跌{abs(change_20):.1f}%)"
        elif change_10 > 2 and change_20 < -3:
            # 整体跌但近期反弹 → 可能止跌
            stage = "pullback"
            desc = f"跌后反弹(近10根涨{change_10:.1f}%，近20根跌{abs(change_20):.1f}%)，关注是否放量止跌"
            if vol_ratio > 1.2:
                desc += "，放量可能为承接点"
        else:
            stage = "sideways"
            desc = f"横盘/震荡(近10根{change_10:+.1f}%，近20根{change_20:+.1f}%)"

    return {
        "stage": stage,
        "description": desc,
        "current_price": current_price,
        "ma5": round(ma5, 6),
        "ma20": round(ma20, 6),
        "volume_ratio": round(vol_ratio, 2),
    }


def format_movers_text(top_n: int = 5) -> str:
    """
    格式化涨跌榜文本，供AI prompt使用。
    返回易读的文本块。
    """
    movers = fetch_top_movers(top_n)
    if not movers["gainers"] and not movers["losers"]:
        return ""

    lines = ["===== 24h 涨跌榜 ====="]

    lines.append(f"\n--- 涨幅榜 Top{top_n} ---")
    for i, g in enumerate(movers["gainers"], 1):
        stage_info = analyze_kline_stage(g["symbol"], is_gainer=True)
        lines.append(f"  {i}. {g['symbol']}  +{g['change_pct']:.2f}%  量:{g['volume']:.0f} USDT")
        lines.append(f"     K线: {stage_info['description']}")
        lines.append(f"     MA5={stage_info['ma5']}  MA20={stage_info['ma20']}  量比={stage_info['volume_ratio']}")

    lines.append(f"\n--- 跌幅榜 Top{top_n} ---")
    for i, loser in enumerate(movers["losers"], 1):
        stage_info = analyze_kline_stage(loser["symbol"], is_gainer=False)
        lines.append(f"  {i}. {loser['symbol']}  {loser['change_pct']:.2f}%  量:{loser['volume']:.0f} USDT")
        lines.append(f"     K线: {stage_info['description']}")
        lines.append(f"     MA5={stage_info['ma5']}  MA20={stage_info['ma20']}  量比={stage_info['volume_ratio']}")

    return "\n".join(lines)


def get_dynamic_candidates(top_n: int = 5, min_volume_usdt: float = 500_000) -> list[str]:
    """
    从涨跌榜实时生成候选币种列表（涨幅榜+跌幅榜的去重合并）。

    优先使用热门的情绪币作为开仓候选，市场在变，候选也在变。
    如果API失败则返回空列表（调用方自行决定fallback）。
    """
    movers = fetch_top_movers(top_n)
    symbols = set()
    for g in movers["gainers"]:
        symbols.add(g["symbol"])
    for loser in movers["losers"]:
        symbols.add(loser["symbol"])
    return list(symbols)
