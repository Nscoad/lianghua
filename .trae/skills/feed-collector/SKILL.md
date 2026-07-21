---
name: "feed-collector"
description: "数据采集层 — 用Selenium从币安广场爬取关注动态并存入JSON。当用户需要获取最新市场动态、爬取广场数据、检查采集状态时调用。"
---

# 数据采集层 — collector/

## 概述

从币安广场（Binance Square）的关注页面爬取最新动态，供 AI 决策层分析使用。

## 文件位置

| 文件 | 说明 |
|------|------|
| `collector/square.py` | Selenium 爬虫实现 |
| `collector/feed_collector.py` | 采集 + 存储的封装（单函数入口） |

## 导出函数

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `get_square_following_feed(max_items=5)` | 爬取关注页最新动态 | `list[str]` |
| `collect_and_store(max_items=10, skip_chrome_check=False)` | 采集 + 去重存储 | `dict{fetched, added, total}` |

## 前置条件

Chrome 必须以调试模式启动（端口 9555），并已登录币安。系统启动时自动检测并启动 Chrome：

```python
# scheduler.py 自动执行
start chrome --remote-debugging-port=9555 --user-data-dir="chrome-debug"
```

## 去重策略

- 根据动态文本**精确去重**（尾部数字变化视为不同内容，保留给AI判断）
- 超过 **1 小时**的动态自动删除（`_clean_expired_feeds`）

## CSS 选择器

当前使用 `div[data-bn-type='text']` 作为动态文本的选择器。币安前端的 class 名是动态混淆的，若页面结构变化需要更新此选择器。

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
