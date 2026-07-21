---
name: "ai-analyzer"
description: "AI决策层 — 调用DeepSeek API分析币安广场动态 + 24h涨跌榜 + 历史波动数据，产出交易信号（buy/sell/hold）+ 强制平仓判断 + 周期复盘分析。当用户需要分析市场情绪、生成交易建议、查看分析结果时调用。"
---

# AI 决策层 — ai/

## 概述

对接 DeepSeek API，通过分析币安广场的最新社交动态 + 24h涨跌榜 + 历史K线波动数据，判断市场情绪并生成交易信号。同时每3分钟检查持仓，判断是否需要强制止盈减仓。每周期汇总时自动复盘分析交易数据。

## 文件位置

| 文件 | 说明 |
|------|------|
| `ai/analyzer.py` | AI开仓分析 — 分析广场动态+涨跌榜产出交易信号（每15分钟）+ 周期复盘分析 |
| `ai/close_analyzer.py` | AI强制平仓 — 检查持仓是否需要强制止盈减仓（每3分钟） |
| `utils/market_screener.py` | 涨跌榜工具 — 提供24h涨跌榜Top5和K线阶段分析（被analyzer依赖） |

## 导出函数

### analyzer.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `run_analysis()` | 完整分析：取未分析动态 + 涨跌榜Top5 + 历史波动 → AI分析 → 保存信号 | `dict` 或 `None` |
| `analyze_with_deepseek(feeds_text, target_symbol, symbol_candidates, movers_text)` | 调用 DeepSeek API 分析给定文本（含涨跌榜数据） | `dict` 或 `None` |
| `analyze_order_error(symbol, side, quantity, error_msg, price, balance, margin)` | **下单失败分析**：将错误上下文发给 DeepSeek，输出失败原因和解决建议 | `None` |
| `analyze_summary_stats(stats)` | **周期复盘分析**：分析统计数据的亏损原因和提升建议，返回 `{root_cause, details, suggestions, adjustment}` | `dict` 或 `None` |

### close_analyzer.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `run_close_analysis_cycle()` | 每3分钟执行的强制平仓分析入口（输出：当前浮盈/止盈/追踪状态 + K线趋势分析） | `None` |
| `analyze_close(symbol)` | 分析单币种持仓是否需强制减仓 | `dict` 或 `None` |
| `_get_holding_symbol()` | 获取当前持仓币种 | `str` 或 `None` |
| `_reduce_position_half(symbol)` | 逐级尝试卖出仓位（50%→40%→30%→20%→10%），找到不超限的比例下单 | `order` 或 `None` |

## AI开仓分析流程

1. 从24h涨跌榜获取**涨幅榜Top5 + 跌幅榜Top5**（`fetch_top_movers`）
2. 分析每个币种的**K线阶段**（刚启动/中段/超跌反弹/横盘）
3. 从广场动态提取文本（如有）
4. 下载候选币种的 **市场数据** + **历史波动数据**
5. 全部交给 DeepSeek 作多币种对比分析（含涨跌榜情绪规则）
6. 输出信号格式：

```json
{
  "sentiment": "bullish | bearish | neutral",
  "confidence": 0-100,
  "reason": "简要分析原因（50字以内）",
  "action": "buy | sell | hold",
  "symbol": "BANKUSDT",
  "reasoning": "详细推理过程"
}
```

**涨跌榜规则**：涨幅榜情绪币容易继续涨，跌幅榜容易继续跌；刚启动比涨了很久的更安全；超跌可能反弹。

## AI强制平仓分析（每3分钟）

- 若有持仓，先打印当前浮盈/止盈状态/追踪激活状态
- 调用 `check_kline_entry()` 分析 K 线趋势（MA6/MA20 判断 up/down/sideways）并输出
- 再调用 DeepSeek 分析当前浮盈 + 市场数据 + 历史波动
- 判断是否 `force_close`（涨幅过大/资金费率转负/ATR飙升/趋势转down）
- 如果需要强制减仓 → 逐级尝试卖出仓位（50%→40%→20%→10%→...）直到不超限

## AI周期复盘分析（汇总报表触发）

每个汇总周期（1h/3h/6h/12h/24h）触发时自动执行：
1. 获取周期统计 `calc_period_stats(hours)`
2. 发送给 DeepSeek 分析亏损原因和提升建议
3. 保存到 `data/analysis_summary.jsonl`（数据库）
4. 随微信汇总报表一起推送

## 历史数据集成

两个分析点都集成历史波动分析：
- `ensure_data_updated(symbol)` — 从 `data.binance.vision` 下载K线到本地SQLite
- `format_volatility_text(symbol)` — 输出AI可读的波动趋势摘要

## 信号存储

信号保存在 `data/trade_signals.json`，可通过 `get_latest_signal()` 获取最新信号。

## Token优化

- 使用 `format_light_market_data()` 精简版市场数据
- 只分析新增动态
- Close Analyzer 的 `max_tokens=200`

## 配置

```python
# config.py
DEEPSEEK_API_KEY = "sk-xxxx"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
```
