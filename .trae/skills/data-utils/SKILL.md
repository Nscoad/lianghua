---
name: "data-utils"
description: "工具层 — SQLite/JSON数据持久化（交易流水、价格快照、K线趋势、日志、微信通知）。当用户需要查看历史数据、检查存储文件、分析盈亏时调用。"
---

# 工具层 — utils/

## 概述

所有数据管理工具，包括：SQLite 交易流水表、价格快照数据库、K线趋势分析、平仓流水记录、日志系统、微信通知。

## 文件位置

| 文件 | 说明 |
|------|------|
| `utils/db.py` | 数据库管理 — SQLite `trade_records` 建表/读写/迁移（含slippage/entry_mode字段） |
| `utils/trade/records.py` | 平仓流水记录 + 开仓记录（含slippage参数） |
| `utils/trade/stats.py` | 交易统计 + 多币种对账 + 周期统计函数 |
| `utils/trade/analysis.py` | AI复盘分析存储到 `analysis_summary.jsonl` |
| `utils/logger.py` | 日志系统（JSONL格式+时间戳+自动清理） |
| `utils/notifier.py` | PushPlus 微信通知（汇总报表 + 趋势摘要） |
| `utils/market/monitor.py` | 全币种价格快照 + 快捞涨跌幅监测 |
| `utils/market/kline.py` | 实时K线趋势判断（MA3/MA6 + K线方向比例） |
| `core/funding.py` | **新增** 资金费率查询与持久化到 funding_records 表 |

## 数据文件

| 文件 | 用途 |
|------|------|
| `data/trading.db` | SQLite 交易记录+日志 |
| `data/market_monitor.db` | SQLite 价格快照（供快捞计算涨跌幅） |
| `data/market_analysis.json` | 市场分析结果（供前端看板） |
| `data/fast_trade_state.json` | 快捞仓位状态 |
| `data/square_feeds.json` | 币安广场+X动态数据 |
| `data/summary_sent_state.json` | 汇总发送状态 |
| `data/analysis_summary.jsonl` | AI复盘分析记录 |

## 关键函数

### db.py

| 函数 | 说明 |
|------|------|
| `init_db()` | 初始化数据库表结构 |
| `insert_trade_record(...)` | 插入平仓记录 |
| `get_trade_records(limit)` | 读取最近N条记录 |
| `get_all_closed_trades()` | 读取所有已平仓记录 |
| `get_trade_records_since(hours)` | 读取指定小时内记录 |

**trade_records 表新增字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `slippage` | REAL DEFAULT 0 | 滑点（市价单成交价与下单前行情价的差值） |
| `entry_mode` | TEXT DEFAULT 'trend' | 入场模式（trend/volatility_override/sideways） |

**funding_records 表结构**（在 `core/funding.py` 中管理）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `time` | TEXT PRIMARY KEY | ISO格式时间 |
| `symbol` | TEXT NOT NULL | 交易对 |
| `side` | TEXT | LONG/SHORT |
| `funding_rate` | REAL | 资金费率 |
| `payment` | REAL | 实际支出（正=支出，负=收入） |
| `mark_price` | REAL | 结算标记价格 |
| `position_qty` | REAL | 持仓数量 |

### records.py (`utils/trade/records.py`)

| 函数 | 说明 |
|------|------|
| `record_open(symbol, side, qty, price, fee, order_id, slippage=0.0)` | 记录开仓 |
| `record_close(symbol, reason, pnl, qty, entry, exit, side, is_partial, fee, order_id, slippage=0.0)` | 记录平仓 |

### stats.py (`utils/trade/stats.py`)

| 函数 | 说明 |
|------|------|
| `calc_period_stats(hours)` | 通用周期统计 |
| `reconcile_trades(since)` | 从交易所对账补漏（扫描所有交易过的币种） |
| `print_summary()` | 打印全部盈亏汇总 |

### notifier.py

| 函数 | 说明 |
|------|------|
| `send_notification(title, content)` | 通过 PushPlus 发送微信通知 |
| `send_summary_report(period_label, stats, ai_analysis)` | 发送周期汇总报表 |
| `send_balance_change_report()` | 发送余额变化通知 |

## 典型使用场景

```python
from utils.trade.records import print_summary, calc_period_stats

# 查看盈亏汇总
print_summary()

# 查看近6小时统计
stats = calc_period_stats(6)
print(stats["total_pnl"], stats["win_rate"])
```
