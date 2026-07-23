"""
信息采集独立脚本 — 手动运行，不随交易系统自动启动

采集币安广场 + X.com 热门动态 → AI 摘要 → 微信通知

用法:
  uv run python run_feed_collector.py          # 单次采集+摘要
  uv run python run_feed_collector.py --loop    # 每30分钟循环采集
  uv run python run_feed_collector.py --collect-only   # 仅采集，不做AI摘要
"""
import sys
import os
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_once(collect_only: bool = False):
    """执行一轮采集（可选是否做AI摘要）"""
    from collector.trend_collector import collect_trends
    from utils.logger import patch_print

    patch_print()
    print("=" * 50)
    print("  信息采集脚本 — 单次执行")
    print("=" * 50)

    # 1. 采集
    results = collect_trends(max_items_per_source=10)
    total = sum(r["fetched"] for r in results.values())
    print(f"\n采集完成，共获取 {total} 条动态\n")

    if collect_only:
        print("--collect-only 模式，跳过 AI 摘要")
        return

    # 2. AI摘要 → 微信通知
    try:
        from ai.analyzer import run_feed_summary
        summary = run_feed_summary()
        if summary:
            print("AI 摘要已发送至微信")
        else:
            print("暂无未分析的动态，跳过 AI 摘要")
    except Exception as e:
        print(f"AI 摘要失败: {e}")


def run_loop(interval: int = 1800):
    """循环采集模式，默认每30分钟一次"""
    from utils.logger import patch_print
    patch_print()

    print("=" * 50)
    print(f"  信息采集脚本 — 循环模式（每 {interval//60} 分钟）")
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    while True:
        try:
            run_once()
        except Exception as e:
            print(f"\n[错误] 采集循环异常: {e}")
            import traceback
            traceback.print_exc()

        print(f"\n等待 {interval//60} 分钟后下一次采集...\n")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="信息采集独立脚本")
    parser.add_argument("--loop", action="store_true", help="循环模式（每30分钟）")
    parser.add_argument("--interval", type=int, default=1800, help="循环间隔（秒，默认1800）")
    parser.add_argument("--collect-only", action="store_true", help="仅采集，不做AI摘要")
    args = parser.parse_args()

    if args.loop:
        run_loop(args.interval)
    else:
        run_once(args.collect_only)
