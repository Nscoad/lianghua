---
name: "master-trader"
description: "交易总调度引擎 — 编排全流程决策（数据源选择→AI分析→执行→风控→汇总复盘），自动判断用广场动态还是纯K线，每次汇总后写入复盘JSON并自适应调整策略。"
---

# Master Trader — 全流程总调度

## 职责

编排所有子模块 skill 的完整执行流程，根据实时条件动态决策数据源，每次汇总后写入复盘 JSON 并自适应调整。

## 全流程流水线

```
① 决策数据源 (decide_data_source)
   ├─ Chrome在线 + ≥3条动态/1h → 广场+K线双源 (confidence+5)
   ├─ Chrome在线 + 动态不足   → 纯K线主导
   └─ Chrome离线             → 纯K线
          ↓
② 采集 (feed-collector)
   └─ 仅在 decide_data_source.use_square=true 时执行
          ↓
③ AI分析 (ai-analyzer)
   ├─ 有广场数据 → prompt注入动态文本
   └─ 纯K线      → prompt仅含涨跌榜+CMC Top10+实时市场数据
          ↓
④ 交易执行 (trade-strategy)
   ├─ 开仓/平仓/切换
   ├─ K线趋势过滤 + 1:3盈亏比止盈(45%保证金) + 保本止损 + 防耗散
   └─ 快捞系统(2min监控, 趋势过滤+冷却)
          ↓
⑤ 风险监控 (core-trader → risk_monitor)
   └─ 1.5秒循环：小止损/TP1首轮止盈/保本止损/防耗散/趋势反转
          ↓
⑥ 汇总复盘 → save_review()
   ├─ 写入 trade_reviews.json
   ├─ 检查 should_switch_strategy()
   └─ 决策反馈到下一轮①
```

## 动态数据源决策逻辑

```
decide_data_source() 返回:
{
  "use_square": bool,       // 本轮是否用广场动态
  "use_kline": true,        // K线永远使用
  "reason": "原因文本",
  "confidence_boost": -10~5, // 信心修正
  "square_available": bool,
  "fresh_feeds": 0~N
}
```

**切换阈值**:
- 最近10笔复盘亏损率 >60% → confidence -10
- 平均胜率 <40% 且总亏损 → 建议切换策略（降杠杆/换币种）

## 复盘数据结构 (trade_reviews.json)

```json
{
  "time": "2026-07-21T12:00:00",
  "period": "1小时",
  "total_trades": 8,
  "total_pnl": 202.48,
  "win_rate": 100.0,
  "long_short": "3多/5空",
  "data_source": "广场动态充足(5条)，双源分析",
  "used_square": true,
  "ai_root_cause": "PROMUSDT贡献主要利润",
  "ai_suggestion": "继续做空PROMUSDT"
}
```

## 子模块调用关系

| 步骤 | 调用的skill | 对应代码模块 |
|------|------------|-------------|
| ① 决策 | — | `utils/trader_orch.py:decide_data_source()` |
| ② 采集 | feed-collector | `collector/feed_collector.py` |
| ③ AI分析 | ai-analyzer | `ai/analyzer.py` (+ CMC: `utils/market_cap.py`) |
| ④ 交易 | trade-strategy | `strategy/auto_trader.py` + `fast_trader.py` |
| ⑤ 风控 | core-trader | `strategy/risk_monitor.py` |
| ⑥ 复盘 | data-utils | `utils/trader_orch.py:save_review()` |

## 每次执行确认清单

每轮全流程执行前，必须依次确认以下事项：

```
□ [复盘检查] 上次汇总 trade_reviews.json 是否存在?
   ├─ 存在 → 读取最后一条复盘记录的 root_cause / suggestion
   ├─ 不存在 → 首次运行，跳过
   └─ → 如果上轮亏损，本轮降低 confidence 10%

□ [收集检查] 本轮数据源是否可用?
   ├─ decide_data_source().use_square = true?
   │  ├─ 是 → 调用 feed-collector 采集广场动态
   │  └─ 否 → 跳过采集，纯 K 线
   ├─ decide_data_source().confidence_boost 应用到 AI 分析
   └─ → 打印最终决策原因

□ [自适应检查] should_switch_strategy() 是否需要调整?
   ├─ switch=true → 执行建议动作（降杠杆/换币种）
   └─ switch=false → 保持当前参数
```

## 自适应调整

每次汇总时自动执行 `should_switch_strategy()`:

| 条件 | 动作 |
|------|------|
| 近6周期平均胜率<40% 且亏损 | 降低杠杆或换币种 |
| 连续3周期亏损 | 减少仓位比例 |
| 胜率>70% 且盈利 | 维持或小幅加仓 |

## 执行示例

```
[master-trader] 第1步 — 复盘检查
  trade_reviews.json 存在，最后一条: 近1h +202.48，建议"继续做空PROMUSDT"
  → 沿用当前策略

[master-trader] 第2步 — 收集检查
  Chrome在线，广场动态 63条 ≥ 3 → 双源分析 (confidence+5)
  → 调用 feed-collector

[master-trader] 第3步 — 自适应检查
  近6周期胜率 72%，总盈利 +129.26 → 维持策略
  → 继续执行 AI分析 → 交易 → 风控 → 汇总复盘
```
