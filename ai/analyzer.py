"""
AI 决策层 — 对接 DeepSeek API，分析广场动态并生成交易信号
"""
import json
from utils.data_manager import get_unanalyzed_feeds, mark_feeds_analyzed, save_signal
from utils.market_screener import format_movers_text, get_dynamic_candidates
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL

SYSTEM_PROMPT = """
你是币安广场分析师。根据最新动态识别热门币种，输出JSON交易信号。

输出格式：
{"symbol":"币种名(带USDT)","sentiment":"bullish/bearish/neutral","confidence":0-100,"reason":"简要原因","action":"buy/sell/hold"}

规则：
- symbol = 讨论热度最高或涨跌榜中最有潜力的币种
- bullish/buy = 多数看涨，情绪积极
- bearish/sell = 多数看跌，恐慌
- neutral/hold = 信息不足或多空均衡
- 结合提供的市场数据（24h涨跌、成交量）和历史波动数据（7天趋势、ATR、主动买入比）综合判断
- 历史和实时数据与情绪一致时提高confidence，矛盾时降低
- 涨跌榜数据：涨幅榜情绪币容易继续涨，跌幅榜情绪币容易继续跌
- K线阶段：刚启动的比已经涨了很久的更安全，超跌的可能反弹
- 参考提供的近期交易记录和AI信号：同一币种连续亏损则降低confidence或换币
- 同一方向的信号反复止损，说明该方向在当前市场环境下成功率低，应减少交易频率
- K线趋势优先于社交情绪：币价实际走势比社交情绪更重要
  - 币种K线趋势向上时（MA6>MA20），即使广场看空也不做空
  - 币种K线趋势向下时（MA6<MA20），即使广场看多也不做多
- 做空（sell）限制：仅当最近4小时K线趋势向下时才考虑做空，上涨趋势中不做空
- 做多（buy）限制：仅当最近4小时K线趋势向上时才考虑做多，下跌趋势中不做多
"""


def analyze_with_deepseek(feeds_text: list[str], target_symbol: str = None,
                          symbol_candidates: list = None, movers_text: str = "") -> dict | None:
    """调用 DeepSeek API 分析动态文本，附带市场数据和历史波动数据"""
    if not DEEPSEEK_API_KEY:
        print("[错误] DEEPSEEK_API_KEY 未配置，跳过分析。")
        return None

    import requests

    user_content = "以下是币安广场最新动态，请分析市场情绪并找出最热门的交易机会：\n\n"
    for i, text in enumerate(feeds_text, 1):
        # 截断长文本，每条最多150字，减少token消耗
        text = text[:150] + ("..." if len(text) > 150 else "")
        user_content += f"[动态 {i}] {text}\n"

    # 涨跌榜数据（情绪币参考）
    if movers_text:
        user_content += f"\n{movers_text}\n"

    # CoinMarketCap 全市场概况
    try:
        from utils.market_cap import format_market_summary
        cmc_text = format_market_summary(top_n=10)
        if cmc_text:
            user_content += f"\n{cmc_text}\n"
    except Exception:
        pass

    # ====== 历史交易数据 ======
    try:
        from utils.trade_records import get_trade_records
        recent = get_trade_records(20)
        if recent:
            user_content += "\n===== 近期交易记录（最近20笔，供复盘参考）=====\n"
            for r in recent[-10:]:
                sym = r.get("symbol", "?")
                side = r.get("side", "?")
                pnl = r.get("net_pnl", r.get("realized_pnl", 0))
                res = "[盈利]" if (pnl or 0) > 0 else "[亏损]"
                user_content += f"  {res} {sym} {side} 盈亏:{pnl:+.2f} 原因:{r.get('reason','?')}\n"
    except Exception:
        pass

    try:
        from utils.data_manager import load_signals
        signals = load_signals()
        if signals:
            user_content += "\n===== 近期AI信号（最近5个）=====\n"
            for s in signals[-5:]:
                user_content += f"  {s.get('symbol','?')} {s.get('action','?')} 信心:{s.get('confidence',0)}% 理由:{s.get('reason','')[:40]}\n"
    except Exception:
        pass

    # 候选币种市场数据（前3个币种，用于AI对比分析）
    if symbol_candidates:
        for sym in symbol_candidates:
            try:
                from utils.market_data import format_light_market_data
                market_info = format_light_market_data(sym)
                user_content += f"\n===== {sym} =====\n"
                if market_info:
                    user_content += f"{market_info}\n"
            except Exception as e:
                user_content += f"\n({sym} 数据获取失败: {e})\n"

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"]

        content = content.strip()

        # 去掉 markdown 代码块包裹
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        # 修复AI输出中常见的JSON格式问题
        import re as re_mod
        # 数字后面多引号: "confidence":85" → "confidence":85
        content = re_mod.sub(r':(\d+)"([,}])', r':\1\2', content)
        # 数字被字符串化: "confidence":"85" → "confidence":85
        content = re_mod.sub(r': "(\d+)"', r': \1', content)

        return json.loads(content)

    except Exception as e:
        print(f"调用 DeepSeek API 失败: {e}")
        return None


def analyze_order_error(symbol: str, side: str, quantity: float, error_msg: str,
                         price: float = 0.0, balance: float = 0.0, margin: float = 0.0):
    """
    下单失败后调用 AI 分析原因。

    将错误信息 + 上下文发给 DeepSeek，解释为什么下单失败。
    """
    if not DEEPSEEK_API_KEY:
        print(f"[下单失败] {symbol} {side} {quantity}: {error_msg}")
        return

    import requests

    prompt = """你是币安合约交易专家。分析下单失败原因，给出简洁诊断。

输出JSON格式：
{"reason":"失败原因一句话","solution":"建议解决方案"}

常见失败原因：
- INSUFFICIENT_BALANCE: 余额不足，不足以支付保证金+手续费
- LOT_SIZE: 数量不符合最小/最大限制或步长要求
- PRICE_FILTER: 价格不符合要求（市价单不常见）
- LEVERAGE: 杠杆倍数不合理
- ORDER_EXISTS: 订单已存在
- MARKET_CLOSED: 交易对暂停
- INVALID_SYMBOL: 币种不支持或退市
"""

    side_label = "买入(BUY)" if side == "BUY" else "卖出(SELL)"
    context = f"""下单失败详情：
- 币种: {symbol}
- 方向: {side_label}
- 数量: {quantity}
- 错误信息: {error_msg}
"""
    if price > 0:
        context += f"- 目标价格: {price}\n"
    if balance > 0:
        context += f"- 账户余额: {balance:.2f} USDT\n"
    if margin > 0:
        context += f"- 开仓保证金: {margin:.2f} USDT\n"

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": context},
                ],
                "temperature": 0.1,
                "max_tokens": 200,
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"]

        # 提取 JSON
        import re
        match = re.search(r'\{[^{}]*\}', content)
        if match:
            raw = match.group().replace("'", '"')
            # 修复常见 JSON 格式问题（数字后面多引号等）
            raw = re.sub(r':(\d+)"([,}])', r':\1\2', raw)
            analysis = json.loads(raw)
            reason = analysis.get("reason", error_msg)
            solution = analysis.get("solution", "")
            print(f"\n[AI诊断] {reason}")
            if solution:
                print(f"[AI建议] {solution}")
        else:
            print(f"\n[AI诊断] {content.strip()}")
    except Exception as e:
        print(f"[AI诊断] API 调用失败: {e}（原始错误: {error_msg}）")


def run_analysis() -> dict | None:
    """执行完整分析流程：取未分析动态 → 涨跌榜 → AI分析 → 生成信号 → 存储"""
    feeds = get_unanalyzed_feeds()
    if not feeds:
        print("[AI分析] 无未分析的动态，尝试用涨跌榜数据辅助判断")
        # 即使没有新动态，也拿涨跌榜数据看是否有机会
        feeds_text = []
    else:
        feeds_text = [f["text"] for f in feeds]
        feed_indices = [i for i, f in enumerate(get_unanalyzed_feeds()) if not f.get("analyzed")]

    # 获取涨跌榜数据
    print("\n  --- 采集涨跌榜数据 ---")
    movers_text = format_movers_text(top_n=5)
    if movers_text:
        print(f"  [涨跌榜] 已获取\n{movers_text}")
    else:
        print("  [涨跌榜] 无数据")

    # 候选币种从涨跌榜实时获取，市场在变候选也在变
    candidates = get_dynamic_candidates(top_n=5)

    # AI分析
    if not feeds_text and not movers_text:
        print("[AI分析] 既无新动态也无涨跌榜数据，跳过")
        return None

    signal = analyze_with_deepseek(feeds_text, symbol_candidates=candidates, movers_text=movers_text)

    if signal:
        # 标记已分析
        if feeds_text and feed_indices:
            mark_feeds_analyzed(feed_indices)
        # 存储信号
        save_signal(signal)
        print(f"\n[AI信号] {signal.get('symbol','?')} {signal.get('action','?')} "
              f"(信心 {signal.get('confidence',0)}%) — {signal.get('reason','')}")
    else:
        print("[AI分析] 未生成有效信号")

    return signal


_SUMMARY_ANALYSIS_PROMPT = """
你是交易复盘专家。根据交易统计数据，分析亏损原因并提出具体的胜率提升建议。

输出JSON格式：
{
    "root_cause": "亏损/盈利的根本原因一句话",
    "details": "更详细的分析（50字以内）",
    "suggestions": "具体改进建议（50字以内）",
    "adjustment": "建议调整的参数（如无则写'暂无'）"
}

分析要点：
- 看止损 vs 止盈的比例：止损多说明入场时机不对或趋势判断错误
- 看多空盈亏：哪边亏损多说明趋势判断有偏向性问题
- 看币种：亏损集中的币种可能不适合当前策略
- 建议要具体可执行，不要空泛
"""


def analyze_summary_stats(stats: dict) -> dict | None:
    """
    AI分析汇总统计数据，找出亏损原因和提升建议。

    Args:
        stats: calc_period_stats() 返回的统计字典

    Returns:
        {"root_cause": str, "details": str, "suggestions": str, "adjustment": str}
        或 None（API失败时）
    """
    if not DEEPSEEK_API_KEY:
        return None
    if not stats or stats.get("total_trades", 0) == 0:
        return None

    import requests

    # 构建统计数据文本
    total = stats["total_trades"]
    win = stats["win"]
    loss = stats["loss"]
    win_rate = stats["win_rate"]
    total_pnl = stats["total_pnl"]
    long_count = stats.get("long_count", 0)
    short_count = stats.get("short_count", 0)
    long_pnl = stats.get("long_pnl", 0)
    short_pnl = stats.get("short_pnl", 0)

    context = f"""过去{stats['period_hours']}小时交易统计：

总平仓: {total}笔
净盈亏: {total_pnl:+.2f} USDT
胜率: {win}胜/{loss}败 ({win_rate}%)

多空:
  做多 {long_count}笔 ({long_pnl:+.2f} USDT)
  做空 {short_count}笔 ({short_pnl:+.2f} USDT)
"""

    if stats.get("by_reason"):
        context += "\n原因分布:\n"
        for r in stats["by_reason"]:
            context += f"  {r['label']}: {r['count']}次 ({r['pnl']:+.2f} USDT, 胜率{r['win_rate']}%)\n"

    if stats.get("by_symbol"):
        context += "\n币种盈亏:\n"
        for s in stats["by_symbol"]:
            context += f"  {s['symbol']}: {s['pnl']:+.2f} USDT ({s['win']}胜/{s['loss']}败/{s['total']}次)\n"

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": _SUMMARY_ANALYSIS_PROMPT},
                    {"role": "user", "content": context},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"]

        import re
        match = re.search(r'\{[^{}]*\}', content)
        if match:
            raw = match.group().replace("'", '"')
            # 修复常见 JSON 格式问题（数字后面多引号等）
            raw = re.sub(r':(\d+)"([,}])', r':\1\2', raw)
            analysis = json.loads(raw)
            return analysis
        return None
    except Exception as e:
        print(f"[AI汇总分析] API调用失败: {e}")
        return None
