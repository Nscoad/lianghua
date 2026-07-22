---
name: "ai-analyzer"
description: 当用户要求"分析下单失败原因""复盘交易""看统计总结""分析交易记录"时必须使用。本 skill 调用 DeepSeek API 提供三个功能：下单失败错误诊断、周期复盘统计AI分析、广场/X动态AI摘要。
---

# AI 决策层 — 错误诊断、复盘分析与消息摘要

对接 DeepSeek API，提供三个独立功能：下单失败后的错误诊断、周期复盘统计的AI分析、广场和X.com动态的AI摘要与微信推送。

## 适用场景

- 用户要求"分析一下这笔交易为什么失败"、"下单报错了看看原因"
- 用户要求"复盘今天的交易"、"写个总结"、"统计一下盈亏"
- 用户要求"看看今天广场什么热点"、"市场有什么新消息"
- 系统自动调用（趋势采集循环每30分钟调 run_feed_summary）
- 系统自动调用（汇总报表循环调 analyze_summary_stats）
- 下单失败时自动调 analyze_order_error

## 安全约定

- DeepSeek API Key 从环境变量读取，不写入任何文件
- 分析结果仅供参考，不构成投资建议

## 输入输出

输入：
- 下单失败的错误信息 + 上下文（币种、方向、数量、错误原因）
- 交易统计数据（周期内盈亏、胜率、多空分布、币种分布）
- 币安广场和X.com最新动态文本

输出：
- 失败原因诊断 + 解决建议（JSON格式）
- 复盘分析（亏损原因 + 改进建议）
- 市场消息摘要 + 热门话题 + 提及币种（微信推送）

## 推荐命令

```python
from ai.analyzer import analyze_order_error, analyze_summary_stats, run_feed_summary

# 下单失败分析
analyze_order_error(symbol, side, quantity, error_msg, price, balance, margin)

# 周期复盘分析
analysis = analyze_summary_stats(stats)

# 市场消息摘要（自动发微信）
result = run_feed_summary()
```

## 文件位置

| 文件 | 说明 |
|------|------|
| `ai/analyzer.py` | 三个AI功能：错误诊断 / 复盘分析 / 消息摘要 |

## 导出函数

### analyzer.py

| 函数 | 说明 |
|------|------|
| `analyze_order_error(symbol, side, quantity, error_msg, price, balance, margin)` | 下单失败 AI 分析原因，输出诊断 + 建议 |
| `analyze_summary_stats(stats)` | 周期（1h/3h/6h/12h/24h）复盘分析，输出亏损原因 + 改进建议 |
| `run_feed_summary()` | 取未分析的市场动态 → DeepSeek摘要 → 发微信通知 → 标记已分析，返回 `{summary, hot_topics, mention_coins}` |

## 执行流程

### 下单失败分析流程

1. 接收下单失败的错误信息（含币种、方向、数量、错误原因）
2. 调用 DeepSeek 分析错误原因（余额不足/数量步长/价格滑点/网络问题等）
3. 输出 JSON: `{"reason": "原因", "solution": "建议"}`
4. 打印到控制台

### 复盘分析流程

1. 接收 `calc_period_stats()` 返回的交易统计字典
2. 提取总平仓数、净盈亏、胜率、多空明细、原因分布、币种分布
3. 调用 DeepSeek 分析亏损原因并给出提升建议
4. 返回 JSON: `{"root_cause", "details", "suggestions", "adjustment"}`

### 市场消息摘要流程

1. 从 `square_feeds.json` 读取未分析的动态文本
2. 取前15条（每条 ≤200字）组装 prompt
3. 调用 DeepSeek 生成摘要
4. 通过 PushPlus 发送微信通知（含摘要、热门话题、提及币种）
5. 标记已分析
6. 返回结构化结果

## 质量标准

- 分析必须基于最新数据
- 下单失败分析必须给出具体原因和可操作建议
- 消息摘要只分析未处理的动态（避免重复推送）
- API 失败时不阻塞调用方，优雅降级打印日志
