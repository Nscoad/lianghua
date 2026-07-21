---
name: "ai-analyzer"
description: 当用户要求"分析市场""看看现在该不该买""交易信号是什么""分析行情""看多还是看空""分析今天市场情绪""交易建议"时必须使用。本 skill 调用 DeepSeek API 分析币安广场动态 + 24h涨跌榜 + 历史波动数据，产出交易信号（buy/sell/hold）+ 周期复盘分析。
---

# AI 决策层 — 市场情绪分析与交易信号

对接 DeepSeek API，分析币安广场社交动态 + 24h涨跌榜 + 实时市场数据，判断市场情绪并生成交易信号。同时支持下单失败分析和周期复盘分析。

## 适用场景

- 用户要求"分析一下现在市场怎么样"、"今天适合做多还是做空"
- 用户要求"看信号"、"交易信号是什么"、"AI 怎么说"
- 用户要求"分析一下这笔交易为什么失败"、"下单报错了看看原因"
- 用户要求"复盘今天的交易"、"写个总结"、"统计一下盈亏"
- 系统自动调用（快捞循环每2分钟触发AI开仓分析）
- 下单失败时自动分析原因

## 安全约定

- DeepSeek API Key 从环境变量读取，不写入任何文件
- 分析结果仅供参考，不构成投资建议
- AI 信号置信度低于 60 时不应执行交易

## 输入输出

输入：
- 币安广场动态文本列表
- 24h 涨跌幅榜 Top5（涨幅 + 跌幅）
- 候选币种历史波动数据
- K线数据
- （可选）下单失败的错误信息

输出：
- 交易信号：`{sentiment, confidence, action, symbol, reason}`
- 周期复盘分析：交易统计 + AI 评语

## 推荐命令

```python
from ai.analyzer import run_analysis, analyze_order_error, analyze_summary_stats

# 执行完整分析
result = run_analysis()
print(f"信号: {result['action']}, 置信度: {result['confidence']}")

# 下单失败分析
analysis = analyze_order_error(symbol, side, quantity, error_msg, price, balance, margin)
```

## 文件位置

| 文件 | 说明 |
|------|------|
| `ai/analyzer.py` | AI开仓分析 + 下单失败分析 + 周期复盘分析 |

## 导出函数

### analyzer.py

| 函数 | 说明 |
|------|------|
| `run_analysis()` | 完整分析：取动态+涨跌榜+市场数据 → AI分析 → 保存信号 |
| `analyze_with_deepseek(feeds_text, target_symbol, symbol_candidates, movers_text)` | 调用 DeepSeek API 分析市场情绪 |
| `analyze_order_error(symbol, side, quantity, error_msg, price, balance, margin)` | 下单失败 AI 分析原因 |
| `analyze_summary_stats(stats)` | 周期（1h/3h/6h/12h/24h）复盘分析 |

## 执行流程

### 开仓分析流程

1. **采集数据**：从 24h 涨跌榜获取涨幅榜 Top5 + 跌幅榜 Top5
2. **K线分析**：分析每个币种的 K 线阶段（刚启动/中段/超跌反弹/横盘）
3. **提取广场动态**：从 `square_feeds.json` 读取最新市场动态文本
4. **获取市场数据**：读取候选币种实时市场数据（价格/24h变化/成交量）
5. **注入 CMC 数据**：CoinMarketCap Top10 全市场排名/1h/24h/7d 涨幅
6. **AI 分析**：全部数据交给 DeepSeek 分析，输出信号
7. **保存信号**：存入 `trade_signals.json`

### 下单失败分析流程

1. 接收下单失败的错误信息（含币种、方向、数量、错误原因）
2. 调用 DeepSeek 分析错误原因（余额不足/价格滑点/网络问题等）
3. 返回分析结果和建议

## 信号格式

```json
{
  "sentiment": "bullish | bearish | neutral",
  "confidence": 0-100,
  "action": "buy | sell | hold",
  "symbol": "BANKUSDT",
  "reason": "简要分析原因"
}
```

## 质量标准

- 置信度低于 60 时不产生交易信号（由策略层过滤）
- 分析必须基于最新数据（广场动态 < 1 小时，涨跌榜 < 5 分钟）
- 下单失败分析必须给出具体原因和可操作建议
