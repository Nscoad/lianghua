"""
采集层 — 15分钟周期趋势采集

从多个数据源获取市场情绪/趋势/热门币信息：
  1. 币安广场主页（热门/最常搜索）
  2. X.com（Twitter）首页推文

存储到同一个 square_feeds.json，供 AI 分析候选币种使用。
"""
from datetime import datetime
from collector.square import get_square_trending_feed
from collector.x_collector import get_x_feed
from utils.data_manager import add_new_feeds


def collect_trends(max_items_per_source: int = 10) -> dict:
    """
    执行一轮趋势采集（广场热门 + X.com）

    收集到的文本会存入 feeds 数据库，供 AI 分析候选币种时使用。

    :param max_items_per_source: 每个数据源最多获取条数
    :return: 采集统计 {source: {fetched, added}}
    """
    results = {}

    print(f"\n--- 15分钟趋势采集 ({datetime.now().strftime('%H:%M:%S')}) ---")

    # 1. 币安广场主页热门
    print("[趋势采集] 币安广场热门动态...")
    square_texts = get_square_trending_feed(max_items=max_items_per_source)
    square_added = 0
    if square_texts:
        square_added = add_new_feeds(square_texts)
    results["square_trending"] = {"fetched": len(square_texts), "added": square_added}
    print(f"  广场热门: 获取 {len(square_texts)} 条，新增 {square_added} 条")

    # 2. X.com 首页推文
    print("[趋势采集] X.com 热门推文...")
    x_texts = get_x_feed(max_items=max_items_per_source)
    x_added = 0
    if x_texts:
        x_added = add_new_feeds(x_texts)
    results["x_feed"] = {"fetched": len(x_texts), "added": x_added}
    print(f"  X推文:   获取 {len(x_texts)} 条，新增 {x_added} 条")

    total_fetched = len(square_texts) + len(x_texts)
    total_added = square_added + x_added
    print(f"  合计:    获取 {total_fetched} 条，新增 {total_added} 条")

    return results
