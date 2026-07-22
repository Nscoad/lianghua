"""
AI 决策层 — 对接 DeepSeek API
  - analyze_order_error: 下单失败后的错误诊断
  - analyze_summary_stats: 周期复盘统计的AI分析
  - run_feed_summary: 广场/X动态AI摘要，发微信通知
"""
import json
import re
from datetime import datetime
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL


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


_FEED_SUMMARY_PROMPT = """
你是一个加密市场新闻摘要助手。根据以下从币安广场和X.com采集的最新动态，生成一份简洁的摘要。

输出JSON格式：
{
    "summary": "一至两句话概括今天的市场热点",
    "hot_topics": ["话题1", "话题2", "话题3"],
    "mention_coins": ["币种1", "币种2"]
}

要求：
- summary 不超过100字
- hot_topics 提取2-3个最热门的话题
- mention_coins 列出动态中提及的币种（带USDT），如无则空数组
"""


def run_feed_summary() -> dict | None:
    """
    分析未处理的广场/X动态，生成AI摘要并发送微信通知。

    流程：取未分析动态 → DeepSeek摘要 → 发微信 → 标记已分析
    """
    try:
        from collector.feeds_db import get_unanalyzed_feeds, mark_feeds_analyzed, load_feeds
    except Exception:
        print("[AI消息摘要] data_manager 不可用，跳过")
        return None

    if not DEEPSEEK_API_KEY:
        print("[AI消息摘要] API KEY 未配置，跳过")
        return None

    feeds = get_unanalyzed_feeds()
    if not feeds:
        return None

    feeds_text = [f["text"] for f in feeds]
    feed_indices = []
    all_feeds = load_feeds()
    for f in all_feeds:
        if not f.get("analyzed") and f["text"] in feeds_text:
            feed_indices.append(all_feeds.index(f))

    # 截断长文本
    full_text = ""
    for i, text in enumerate(feeds_text[:15], 1):
        text = text[:200] + ("..." if len(text) > 200 else "")
        full_text += f"[动态 {i}] {text}\n"

    try:
        import requests
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": _FEED_SUMMARY_PROMPT},
                    {"role": "user", "content": f"以下是来自币安广场和X.com的最新动态：\n{full_text}"},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        m = re.search(r"\{.*\}", content, re.DOTALL)
        result = json.loads(m.group()) if m else {"summary": content[:100], "hot_topics": [], "mention_coins": []}

        # 构建微信消息
        summary_text = result.get("summary", "")
        topics = result.get("hot_topics", [])
        coins = result.get("mention_coins", [])

        wx_lines = [
            "<h3>🗞️ 市场消息速递</h3>",
            f"<b>时间:</b> {datetime.now().strftime('%H:%M')}<br>",
            "<b>来源:</b> 币安广场 + X.com<br>",
            "<hr>",
            f"<b>📌 摘要</b><br>{summary_text}<br>",
        ]
        if topics:
            wx_lines.append(f"<hr><b>🔥 热门话题</b><br>{'、'.join(topics)}<br>")
        if coins:
            wx_lines.append(f"<hr><b>🪙 提及币种</b><br>{'、'.join(coins)}<br>")
        wx_lines.append(f"<hr><span>共分析 {len(feeds_text)} 条动态</span>")

        content_text = "\n".join(wx_lines)

        from utils.notifier import send_notification
        send_notification("🗞️ 市场消息速递", content_text)

        print(f"  [AI消息摘要] {summary_text[:60]}...")
        print("  [微信] 通知已发送")

        # 标记已分析
        if feed_indices:
            mark_feeds_analyzed(feed_indices)

        return result

    except Exception as e:
        print(f"[AI消息摘要] 失败: {e}")
        return None
