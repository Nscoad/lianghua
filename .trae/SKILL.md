---
name: "lianghua"
description: "AI驱动的币安U本位合约自动化交易系统 — 多层架构量化交易框架，包含采集层/决策层/策略层/行动层/工具层。当用户询问项目整体结构、架构设计或系统功能时调用。"
---

# 数字货币量化交易系统 (lianghua)

## 这是什么？

一个基于 **Binance U本位合约** 的全自动量化交易系统。由 **AI（DeepSeek）** 驱动，通过分析币安广场社交动态 + 24h涨跌榜 + 历史K线波动数据，自动判断市场情绪并执行交易。

**一句话**：采集广场 → 涨跌榜 → AI分析 → 5x自动交易（20%仓位）→ 3秒动态风控 → 1h/3h/6h/12h/24h微信汇总。

## 核心能力

| 能力 | 说明 |
|------|------|
| 🤖 AI情绪分析 | DeepSeek 分析广场动态+涨跌榜，自动识别热点币种和市场情绪 |
| 📊 24h涨跌榜 | 实时获取涨跌幅Top5，分析K线阶段（刚启动/中段/超跌反弹/横盘） |
| ⚡ 自动交易执行 | 信号确认延迟(120s)、K线趋势过滤/横盘换动态候选币、冷却双确认、交易所数量限制、服务器止损单 |
| 🛡️ 动态风控 | 3秒循环：止损(-30%保证金) → 止盈(+40%减仓55%) → 追踪止损(50%激活/15%回撤) |
| 🔄 AI强制止盈 | 每3分钟AI判断是否涨幅过大 → 逐级减仓 |
| 📊 定时微信汇总 | 1h/3h/6h/12h/24h推送盈亏表+多空比+AI复盘分析至微信 |
| 🔐 异常恢复 | 自动时间同步(-1021错误)、下单失败AI诊断、日志JSONL持久化 |
| ⚡ API速率限制 | 全局200ms间隔，5秒内存缓存 |

## 6个子模块

本项目的 `.trae/skills/` 下包含 **6个技能模块**，按架构层次严格划分：

### 1. 行动层 — [core-trader](skills/core-trader/SKILL.md)
**文件**: `core/trader.py`
> 币安 API 最底层封装。查余额、查价格、下单、设止损单、查持仓。

### 2. 采集层 — [feed-collector](skills/feed-collector/SKILL.md)
**文件**: `collector/square.py` + `feed_collector.py`
> Selenium 爬取币安广场关注动态，去重+1小时过期清理。

### 3. AI决策层 — [ai-analyzer](skills/ai-analyzer/SKILL.md)
**文件**: `ai/analyzer.py` + `close_analyzer.py` + `utils/market_screener.py`
> DeepSeek API 调用。开仓分析(15分钟) + 强制平仓分析(3分钟) + 周期复盘分析。

### 4. 策略层 — [trade-strategy](skills/trade-strategy/SKILL.md)
**文件**: `strategy/auto_trader.py` + `risk_monitor.py` + `risk_manager.py`
> 交易执行 + 3秒高频风控。信号确认、冷却双确认、止损止盈、追踪止损、服务器止损。

### 5. 工具层 — [data-utils](skills/data-utils/SKILL.md)
**文件**: `utils/data_manager.py` + `market_data.py` + `market_screener.py` + `historical_data.py` + `trade_records.py` + `notifier.py` + `logger.py`
> 所有数据管理：JSON持久化、实时行情、涨跌榜、历史K线SQLite、平仓流水、日志、微信汇总。

### 6. 系统总览 — [crypto-trader](skills/crypto-trader/SKILL.md)
> 项目全局说明。4个并行循环、启动方式、架构图、调用指引。

## 目录结构

```
lianghua/
├── .trae/
│   ├── SKILL.md                        # ← 本文件 — 系统总览
│   └── skills/
│       ├── core-trader/SKILL.md        # 行动层
│       ├── feed-collector/SKILL.md     # 采集层
│       ├── ai-analyzer/SKILL.md        # AI决策层
│       ├── trade-strategy/SKILL.md     # 策略层
│       ├── data-utils/SKILL.md         # 工具层
│       └── crypto-trader/SKILL.md      # 系统总览
├── core/trader.py          # 行动层 — 币安API
├── ai/
│   ├── analyzer.py         # AI决策层 — 开仓分析 + 复盘分析
│   └── close_analyzer.py   # AI决策层 — 强制平仓
├── collector/
│   ├── square.py           # 采集层 — 爬虫
│   └── feed_collector.py   # 采集层 — 存储封装
├── strategy/
│   ├── auto_trader.py      # 策略层 — 交易执行（含冷却双确认）
│   ├── risk_monitor.py     # 策略层 — 3秒风控
│   └── risk_manager.py     # 策略层 — 状态持久化（含冷却）
├── utils/
│   ├── data_manager.py     # 工具层 — JSON管理
│   ├── market_data.py      # 工具层 — 实时行情
│   ├── market_screener.py  # 工具层 — 涨跌榜Top5 + K线阶段
│   ├── historical_data.py  # 工具层 — 历史K线
│   ├── trade_records.py    # 工具层 — 流水统计 + AI分析
│   ├── notifier.py         # 工具层 — 微信定时汇总报表
│   └── logger.py           # 工具层 — 日志系统
├── config.py               # 全局配置
├── scheduler.py            # 调度器(4个并行循环)
├── check_balance.py        # 快捷查余额
├── check_symbol.py         # 快捷查交易对信息
└── data/                   # 运行时数据(自动生成)
    ├── square_feeds.json   # 广场动态
    ├── trade_signals.json  # 交易信号
    ├── risk_state.json     # 风控状态
    ├── trade_records.jsonl # 平仓流水
    ├── analysis_summary.jsonl # AI复盘分析
    ├── historical.db       # 历史K线
    └── run_log.jsonl       # 运行日志
```

## 4个并行守护循环

| 循环 | 频率 | 职责 | 代码入口 |
|------|------|------|----------|
| **AI分析循环** | 每15分钟 | 涨跌榜+采集+AI分析+开新仓（空仓立即建仓） | `analysis_loop()` |
| **市场分析循环** | 每3分钟 | 持仓检查+强制止盈 | `market_loop()` |
| **风险监控循环** | 每3秒 | 止损30%/止盈40%/追踪50%/回撤15% | `risk_loop()` |
| **汇总报表循环** | 每分钟检查 | 到点发1h/3h/6h/12h/24h微信汇总（含AI复盘） | `summary_loop()` |

## 启动方式

```bash
# 生产模式 — 4个循环并行运行
uv run python scheduler.py forever

# 单次执行 — 跑一轮就退出
uv run python scheduler.py

# 查看交易统计
uv run python -c "from utils.trade_records import print_summary; print_summary()"
```

## 更新说明

> **重要**：更新代码后，需同步更新 `.trae/skills/` 下相关 SKILL.md，确保与实际代码一一对应。
>
> 修改哪个模块的文件，就去更新对应层次的 SKILL.md。新增文件时需同时更新 `data-utils` 或上层模块的说明。
