---
name: "lianghua"
description: "AI驱动的币安U本位合约自动化交易系统 — 快捞策略(涨7.3%追涨杀跌) + 5秒持仓监控 + 动态锁仓止盈 + 滑点/资金费率追踪 + 微信通知。当用户询问项目整体结构、架构设计或系统功能时调用。"
---

# 数字货币量化交易系统 (lianghua)

## 这是什么？

一个基于 **Binance U本位合约** 的全自动量化交易系统。核心策略为**快捞**：每2分钟扫描500+币种，15分钟涨>7.3%做多、跌>7.3%做空，小仓追涨杀跌 + K线动态锁仓止盈 + 5秒持仓监控 + 滑点/资金费率追踪。趋势采集已独立为 `run_feed_collector.py` 脚本，按需运行。

**一句话**：快捞(2min监测7.3%涨跌) + 动态锁仓(K线波动算回撤) + 5秒持仓监控 + 滑点/资金费率追踪 + 定时汇总(1h/3h/6h/12h/24h)。

## 核心能力

| 能力 | 说明 |
|------|------|
| ⚡ 快捞策略 | 每2分钟监测500+币种，15min涨>7.3%做多/跌>7.3%做空，小仓追涨杀跌 |
| 🛡️ K线动态锁仓 | 利润<10%不锁，10~30%阶梯锁，≥30%固定5%价格回撤 |
| 🔄 冷却机制 | 止损后冷却30分钟，趋势匹配可提前解除 |
| 📝 入场模式 | 记录 trend/volatility_override/sideways 三种入场模式，供后续分析 |
| 💰 滑点/资金费率 | 跟踪每笔交易的滑点成本和资金费率支出 |
| 🔍 实盘价格 | 测试网模式下用实盘真实价格做持仓检查，避免深度失真 |
| 📋 定时微信汇总 | 1h/3h/6h/12h/24h推送盈亏/多空/原因分布/AI复盘分析至微信 |
| 🔐 异常恢复 | 自动时间同步(-1021)、下单失败AI诊断、启动时自动对账 |
| 🖥️ 前端看板 | Flask实时看板，展示余额/仓位/市场概况/日志 |

## 7个子模块

本项目 `.trae/skills/` 下包含 **7个技能模块**：

### 1. 行动层 — [core-trader](skills/core-trader/SKILL.md)
**文件**: `core/client.py` + `core/queries.py` + `core/order.py` + `core/funding.py`
> 币安 API 封装：client（客户端/限流/时间同步）→ queries（余额/价格/持仓/币种限制）→ order（下单/平仓/止损/分批拆单）→ funding（资金费率检查）。

### 2. 快捞策略 — [trade-strategy](skills/trade-strategy/SKILL.md)
**文件**: `utils/trade/fast_trader.py`
> 快捞核心逻辑：15分钟涨>7.3%做多/跌>7.3%做空，K线趋势过滤，动态锁仓止盈，冷却机制，入场模式记录。

### 3. 采集层 — [feed-collector](skills/feed-collector/SKILL.md)
**文件**: `collector/square.py` + `run_feed_collector.py` + `trend_collector.py` + `x_collector.py` + `feeds_db.py`
> Selenium 爬取币安广场 + X.com 动态，去重存储，过期清理。

### 4. AI决策层 — [ai-analyzer](skills/ai-analyzer/SKILL.md)
**文件**: `ai/analyzer.py`
> DeepSeek API 调用：下单错误诊断 + 周期复盘分析 + 广场X动态摘要。

### 5. 工具层 — [data-utils](skills/data-utils/SKILL.md)
**文件**: `utils/db.py` + `trade/` + `market/` + `notifier.py` + `logger.py`
> 所有数据管理：SQLite交易流水、价格快照、K线趋势、日志、微信通知。

### 6. 交易系统整合 — [crypto-trader](skills/crypto-trader/SKILL.md)
**文件**: 各模块的整合入口
> AI驱动的币安U本位合约自动化交易系统完整封装，包含快捞策略、K线动态锁仓、趋势采集AI摘要、微信通知等全部功能。

### 7. 前端看板 — [web-dashboard](skills/web-dashboard/SKILL.md)
**文件**: `web_dashboard/`
> Flask实时看板，展示余额/仓位/市场概况/日志。

## 目录结构

```
lianghua/
├── .trae/
│   ├── SKILL.md                        # ← 本文件 — 系统总览
│   └── skills/
│       ├── core-trader/SKILL.md        # 行动层
│       ├── trade-strategy/SKILL.md     # 快捞策略
│       ├── feed-collector/SKILL.md     # 采集层
│       ├── ai-analyzer/SKILL.md        # AI决策层
│       ├── data-utils/SKILL.md         # 工具层
│       ├── crypto-trader/SKILL.md      # 交易系统整合
│       └── web-dashboard/SKILL.md      # 前端看板
├── core/
│   ├── client.py        # 行动层 — 客户端/限流/时间同步
│   ├── queries.py       # 行动层 — 余额/价格/持仓/币种限制
│   ├── order.py         # 行动层 — 下单/平仓/止损
│   └── funding.py       # 行动层 — 资金费率检查
├── ai/analyzer.py       # AI决策层 — 错误诊断/复盘/摘要
├── collector/
│   ├── square.py           # 采集层 — 币安广场爬虫
│   ├── x_collector.py      # 采集层 — X.com采集
│   ├── feeds_db.py         # 采集层 — 数据管理
│   └── ...                 # 其他采集相关文件
├── utils/
│   ├── db.py               # 工具层 — 数据库管理
│   ├── logger.py           # 工具层 — 日志
│   ├── notifier.py         # 工具层 — 微信通知
│   ├── trade/
│   │   ├── fast_trader.py  # 快捞策略 — 核心交易逻辑
│   │   ├── records.py      # 工具层 — 平仓流水
│   │   ├── stats.py        # 工具层 — 交易统计+对账
│   │   └── analysis.py     # 工具层 — 复盘分析存储
│   └── market/
│       ├── monitor.py      # 工具层 — 价格快照+快捞监测
│       └── kline.py        # 工具层 — K线趋势判断
├── web_dashboard/          # 前端看板
├── config.py               # 全局配置
├── scheduler.py            # 调度器(快捞+汇总循环)
├── run_feed_collector.py   # 趋势采集独立脚本
└── data/                   # 运行时数据
```

## 2个并行守护循环

| 循环 | 频率 | 职责 | 代码入口 |
|------|------|------|----------|
| **快捞循环** | 每2分钟 | 监测500+币种，15min涨>7.3%做多/跌>7.3%做空 | `fast_loop()` |
| **汇总报表循环** | 每分钟检查 | 到点发1h/3h/6h/12h/24h微信汇总（含AI复盘） | `summary_loop()` |

## 启动方式

```bash
# 生产模式
uv run python scheduler.py forever

# 看板
uv run python run_dashboard.py

# 信息采集（独立运行）
uv run python run_feed_collector.py          # 一次采集+AI摘要
uv run python run_feed_collector.py --loop   # 循环模式
```

## 更新说明

> **重要**：更新代码后，需同步更新 `.trae/skills/` 下相关 SKILL.md，确保与实际代码一一对应。
>
> 修改哪个模块的文件，就去更新对应层次的 SKILL.md。
