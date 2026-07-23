---
name: "feed-collector"
description: "数据采集层 — 用Selenium从币安广场爬取关注动态 + X.com采集。当用户需要获取最新市场动态、爬取广场数据、检查采集状态时调用。"
---

# 数据采集层 — collector/

## 概述

从币安广场（Binance Square）和 X.com 采集最新市场动态，供 AI 摘要使用。

## 文件位置

| 文件 | 说明 |
|------|------|
| `collector/square.py` | Selenium 爬虫实现（币安广场） |
| `collector/x_collector.py` | X.com 首页推文采集 |
| `collector/trend_collector.py` | 趋势数据整合函数 |
| `collector/feed_collector.py` | 采集 + 存储的封装 |
| `collector/feeds_db.py` | 采集数据管理（去重/过期清理） |
| `run_feed_collector.py` | 独立运行入口 |

## 运行方式

```bash
# 单次采集 + AI摘要 → 微信
uv run python run_feed_collector.py

# 仅采集，不做AI摘要
uv run python run_feed_collector.py --collect-only

# 循环模式（每30分钟自动采集）
uv run python run_feed_collector.py --loop
```

## 导出函数

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `get_square_following_feed(max_items=5)` | 爬取关注页最新动态 | `list[str]` |
| `collect_and_store(max_items=10, skip_chrome_check=False)` | 采集广场 → 去重存储 | `dict` |
| `collect_trends(max_items_per_source=10)` | 采集广场 + X.com → 合并存储 | `dict` |

## 前置条件

- Chrome 需以调试模式启动（端口 9555），并已登录币安和 X.com
- `run_feed_collector.py` 启动时自动检测 Chrome 状态
- 不再由系统启动时自动检查 Chrome 状态

## 去重策略

- 根据动态文本**精确去重**
- 超过 **1 小时**的动态自动删除

## 存储格式

```json
[
  {
    "text": "动态内容...",
    "fetched_at": "2026-07-20T00:30:00",
    "analyzed": false,
    "analyzed_at": null
  }
]
```
