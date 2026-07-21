---
name: "data-utils"
description: "工具层 — JSON/JSONL/SQLite数据持久化（市场数据、历史波动、平仓流水、日志）。当用户需要查看历史数据、读取信号、检查存储文件、分析盈亏时调用。"
---

# 工具层 — utils/

## 概述

所有数据管理工具，包括：JSON数据读写、历史K线数据库、实时市场数据、平仓流水记录、带时间戳的日志系统、定时微信汇总报表。

## 文件位置

| 文件 | 说明 |
|------|------|
| `utils/data_manager.py` | JSON 文件数据管理（广场动态、交易信号） |
| `utils/market_data.py` | 实时市场数据（轻量版） |
| `utils/market_screener.py` | 24h涨跌榜Top5 + K线阶段分析 |
| `utils/historical_data.py` | 历史K线数据库（从 data.binance.vision 下载至 SQLite） |
| `utils/trade_records.py` | 平仓流水记录 + 多周期统计 + AI汇总分析 |
| `utils/logger.py` | 日志系统（JSONL格式+时间戳+自动清理） |
| `utils/notifier.py` | PushPlus 微信通知（定时汇总报表，不再单笔通知） |

## 数据文件

| 文件 | 用途 |
|------|------|
| `data/square_feeds.json` | 币安广场动态数据 |
| `data/trade_signals.json` | AI 交易信号历史 |
| `data/risk_state.json` | 风险管理状态（由 strategy/risk_manager.py 维护）|
| `data/trade_records.jsonl` | 平仓流水（逐笔追加） |
| `data/analysis_summary.jsonl` | AI复盘分析记录（逐周期追加，含 root_cause/suggestions） |
| `data/historical.db` | SQLite 历史K线数据库 |
| `data/run_log.jsonl` | 运行日志（每次启动新文件） |

### notifier.py — 微信定时汇总报表

| 函数 | 说明 |
|------|------|
| `send_notification(title, content)` | 通过 PushPlus 发送微信通知，token 为空或失败时静默返回 False |
| `send_summary_report(period_label, stats, ai_analysis=None)` | 发送周期汇总报表（总览/多空比/原因分布/币种明细/AI复盘分析） |

## 各模块详情

### data_manager.py — JSON持久化

| 函数 | 说明 |
|------|------|
| `load_feeds()` | 加载所有动态 |
| `save_feeds(feeds)` | 覆盖保存动态列表 |
| `add_new_feeds(new_texts)` | 追加新动态（按内容去重，尾部数字变化保留） |
| `get_unanalyzed_feeds()` | 获取未分析动态 |
| `mark_feeds_analyzed(indices)` | 标记已分析 |
| `load_signals()` | 加载所有历史信号 |
| `save_signal(signal)` | 追加一条信号 |
| `get_latest_signal()` | 获取最新信号 |

### market_data.py — 实时行情

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `format_light_market_data(symbol)` | 格式化轻量版市场数据（供AI分析） | `str` |

### market_screener.py — 涨跌榜

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `fetch_top_movers(top_n=5)` | 从交易所获取24h涨跌幅榜Top5（涨幅榜+跌幅榜） | `(list, list)` |
| `analyze_kline_stage(symbol, is_gainer)` | 分析单个币种的K线阶段（刚启动/中段/超跌反弹/横盘） | `dict` |
| `format_movers_text(top_n=5)` | 格式化涨跌榜文本（供AI prompt使用） | `str` |
| `get_dynamic_candidates(top_n=5)` | 从涨跌榜实时获取候选币种列表 | `list[str]` |

### historical_data.py — 历史波动 + K线入场分析

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `update_historical_data(symbol, days)` | 从 data.binance.vision 下载K线到 SQLite | `int` |
| `get_volatility_analysis(symbol, lookback_hours)` | 波动率分析（趋势/波动率/ATR/成交量变化/主动买入比） | `dict` |
| `format_volatility_text(symbol)` | 格式化波动分析文本（AI可读，约8行） | `str` |
| `ensure_data_updated(symbol)` | 检查当天数据，无则下载 | `None` |
| `check_kline_entry(symbol, want_long)` | **K线入场分析**：MA6/MA20趋势判断 + 放量突破/横盘检测，返回 `enter/wait/skip` | `dict` |
| `check_kline_entry_main(symbol, want_long, candidates)` | **K线主入口**：先查主币种K线，横盘等180秒重查，仍横盘尝试候选币种 | `dict` |

### trade_records.py — 平仓流水

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `record_close(symbol, reason, pnl, qty, entry, exit, side, is_partial, fee=0.0, order_id=0)` | 记录一笔平仓（含手续费、净盈亏 `net_pnl`、订单ID） | `None` |
| `record_open(symbol, side, qty, price, fee=0.0, order_id=0)` | **记录开仓**（含手续费，`realized_pnl=0`, `net_pnl=-fee`） | `None` |
| `print_summary()` | 打印全部盈亏汇总 | `None` |
| `calc_period_stats(hours)` | 通用周期统计：指定小时内的盈亏/多空比/原因分布/币种明细 | `dict` 或 `None` |
| `get_trade_records(limit)` | 读取最近 N 条平仓记录 | `list[dict]` |
| `reconcile_trades(symbols)` | **交易所对账**：从交易所拉取所有成交，自动补记缺失的开仓/平仓记录 | `None` |
| `save_summary_analysis(period_label, stats, ai_analysis)` | 保存AI复盘分析到 `analysis_summary.jsonl` | `None` |

### logger.py — 日志系统

| 函数 | 说明 |
|------|------|
| `patch_print()` | 替换 print 为带时间戳 + 写入 JSONL |
| `flush_log()` | 强制刷日志缓冲区 |
| 自动清理 | 超过7天的日志自动删除 |

## 典型使用场景

```python
from utils.trade_records import print_summary, calc_period_stats

# 查看盈亏汇总
print_summary()

# 查看近6小时统计
stats = calc_period_stats(6)
print(stats["total_pnl"], stats["win_rate"], stats["long_count"], stats["short_count"])
```
