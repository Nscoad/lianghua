"""
采集层 — 收集广场动态并存入 JSON
"""
from collector.square import get_square_following_feed, ensure_chrome_debug
from utils.data_manager import add_new_feeds, load_feeds


def collect_and_store(max_items: int = 10, skip_chrome_check: bool = False) -> dict:
    """
    收集广场动态并存储到 JSON
    :param max_items: 获取动态条数
    :param skip_chrome_check: 跳过 Chrome 检测（循环时如已成功过可跳过）
    :return: 收集结果统计
    """
    if not skip_chrome_check:
        if not ensure_chrome_debug():
            print("[错误] Chrome 调试模式不可用，跳过采集。")
            return {"fetched": 0, "added": 0, "total": len(load_feeds())}

    print("\n--- 正在获取广场关注动态 ---")
    new_texts = get_square_following_feed(max_items=max_items)

    if not new_texts:
        print("未获取到新动态。")
        return {"fetched": 0, "added": 0, "total": len(load_feeds())}

    added = add_new_feeds(new_texts)
    total = len(load_feeds())

    print(f"获取到 {len(new_texts)} 条动态，新增 {added} 条，累计 {total} 条")

    return {"fetched": len(new_texts), "added": added, "total": total}
