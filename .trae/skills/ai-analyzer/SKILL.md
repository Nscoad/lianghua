---
name: "ai-analyzer"
description: "AI决策层 — 调用DeepSeek API进行下单错误诊断 + 周期复盘分析 + 广场X动态摘要。当用户需要分析市场情绪、生成交易建议、查看分析结果时调用。"
---

# AI 决策层 — ai/analyzer.py

## 概述

对接 DeepSeek API，提供三个独立功能：
1. **下单错误诊断**：下单失败时分析原因并给出解决建议
2. **周期复盘分析**：汇总周期触及时分析交易数据，找亏损原因
3. **广场X摘要**：分析采集的动态，生成摘要发微信（独立脚本，按需运行）

## 文件位置

`ai/analyzer.py`

## 导出函数

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `analyze_order_error(symbol, side, quantity, error_msg, price, balance, margin)` | **下单失败分析**：将错误上下文发给 DeepSeek，输出失败原因和解决建议 | `None` |
| `analyze_summary_stats(stats)` | **周期复盘分析**：分析统计数据的亏损原因和提升建议，返回 `{root_cause, details, suggestions, adjustment}` | `dict` 或 `None` |
| `run_feed_summary()` | **广场X摘要**：取未分析动态 → DeepSeek 生成热点摘要 → 微信通知 | `dict` 或 `None` |

## 运行方式

| 功能 | 触发 | 频率 |
|------|------|------|
| 下单错误诊断 | `core/order.py` 下单失败时自动调用 | 按需 |
| 周期复盘分析 | `scheduler/loops.py` 汇总报表循环 | 1h/3h/6h/12h/24h |
| 广场X摘要 | `run_feed_collector.py`（独立脚本） | 按需或 `--loop` 循环模式 |

## 配置

```python
# config.py
DEEPSEEK_API_KEY = "sk-xxxx"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
```
