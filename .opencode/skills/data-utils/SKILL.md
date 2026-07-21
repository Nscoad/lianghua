---
name: "data-utils"
description: 当用户要求"查看历史数据""读取信号""检查存储文件""分析盈亏""查看统计""看日志""查看交易记录""查对账单""运行对账"时必须使用。本 skill 管理所有数据持久化工具：JSON/JSONL/SQLite 数据读写、历史K线、市场数据、平仓流水、统计、日志、微信通知、全场币种监控。
---

# 工具层 — 数据管理与工具函数

所有数据管理工具：JSON数据读写、历史K线数据库、实时市场数据、平仓流水、交易统计、日志、微信通知、全场币种监控。

## 适用场景

- 用户要求"看看我的交易记录"、"查一下盈亏统计"
- 用户要求"检查数据文件"、"看下信号存哪里了"
- 用户要求"分析历史K线"、"下载历史数据"
- 用户要求"发个微信通知"、"推送消息到微信"
- 用户要求"监控全场币种"、"检测异常涨幅"
- 用户要求"对账"、"修复交易记录"
- 系统自动调用：市场监控每小时、快捞每2分钟、行情数据下载
- Web Dashboard 通过本层提供的 API 展示实时数据

## 安全约定

- 所有数据存储在 `data/` 目录下
- 微信通知使用 PushPlus 服务，token 从配置文件读取
- 不修改交易所原始数据，只做本地持久化
- 对账操作不会删除已有记录，只会补充缺失记录

## 输入输出

输入：数据查询参数（周期/币种/时间范围）
输出：JSON/SQLite 数据文件或格式化统计结果

## 数据文件一览

| 文件 | 用途 | 格式 |
|------|------|------|
| `data/square_feeds.json` | 币安广场动态 | JSON |
| `data/trade_signals.json` | AI 交易信号 | JSON |
| `data/risk_state.json` | 风险管理状态 | JSON |
| `data/market_monitor.db` | 币种价格快照 | SQLite |

## 推荐命令

```python
from utils.trade_stats import print_summary, calc_period_stats, reconcile_trades
from utils.trade_records import record_open, record_close
from utils.market_monitor import run_market_monitor, run_fast_monitor

# 查看交易统计
print_summary()

# 查看1小时统计
stats = calc_period_stats(hours=1)

# 对账
reconcile_trades()

# 全场监控
run_market_monitor()
```

## 文件位置及导出函数

### 数据管理

| 文件 | 主要函数 | 说明 |
|------|---------|------|
| `utils/data_manager.py` | `load_data()`, `save_data()` | JSON 文件数据管理 |
| `utils/market_data.py` | 实时价格查询（轻量版） | — |
| `utils/market_screener.py` | `fetch_top_movers()`, `analyze_kline_stage()`, `get_dynamic_candidates()` | 24h涨跌榜 + K线阶段分析 |
| `utils/historical_data.py` | `check_kline_entry()` | 实时K线入场分析（MA3/MA6趋势 + 放量突破判断） |

### 交易记录与统计

| 文件 | 主要函数 | 说明 |
|------|---------|------|
| `utils/trade_records.py` | `record_close()`, `record_open()` | 开平仓流水记录 |
| `utils/trade_stats.py` | `calc_period_stats()`, `print_summary()`, `reconcile_trades()` | 交易统计 + 对账 |
| `utils/trade_analysis.py` | `save_summary_analysis()` | AI复盘分析存储 |

### 监控与通知

| 文件 | 主要函数 | 说明 |
|------|---------|------|
| `utils/market_monitor.py` | `run_market_monitor()`, `run_fast_monitor()`, `get_all_usdt_symbols()` | 全场币种涨幅监控 |
| `utils/fast_trader.py` | `try_fast_open()`, `try_fast_short()`, `check_fast_position()` | 快捞交易执行 |
| `utils/notifier.py` | `send_summary_report()`, `send_wechat_msg()` | PushPlus 微信通知 |
| `utils/logger.py` | `patch_print()`, `flush_log()` | 日志系统 |

## 关键功能说明

### 市场数据（market_screener.py）
- `fetch_top_movers(top_n=5)`：24h涨跌幅榜Top5（涨幅+跌幅）
- `analyze_kline_stage(symbol, is_gainer)`：K线阶段分析（刚启动/中段/超跌反弹/横盘）
- `get_dynamic_candidates(top_n=5)`：动态候选币种

### 历史K线（historical_data.py）
- `check_kline_entry(symbol, want_long)`：实时K线入场分析（MA3/MA6趋势/横盘判断/放量突破）
- 数据源：币安实时API fapi/v1/klines（30秒缓存），非历史CSV
- `get_kline_levels(symbol, lookback=24)`：1h K线前高前低 + 盘整判断（供风控使用）

### 交易统计（trade_stats.py）
- `calc_period_stats(hours)`：多周期（1h/3h/6h/12h/24h）交易统计
- `print_summary()`：盈亏汇总输出
- `reconcile_trades()`：交易所对账补记（启动时自动调用）

### 全场监控（market_monitor.py）
- `run_market_monitor()`：每小时检测所有币种 1h 涨幅 > 50%，微信推送预警
- `run_fast_monitor()`：每2分钟监测 500+ 币种，15min涨>6% 做多 / 跌>6% 做空（含趋势过滤+冷却）
- `get_all_usdt_symbols()`：获取所有 USDT 永续合约实时价格

### 快捞交易（fast_trader.py）
- `try_fast_open(symbol, price, prev_price)`：快速开多（5%余额，15min涨>6%触发 + K线up趋势）
- `try_fast_short(symbol, price, prev_price)`：快速做空（5%余额，15min跌>6%触发 + K线down趋势）
- `check_fast_position()`：检查快仓位止盈+3%平一半/1%追踪止损/-1.5%止损（含冷却机制）

### 微信通知（notifier.py）
- `send_summary_report(period_label, stats, ai_analysis=None)`：微信汇总报表
- `send_wechat_msg(title, content)`：通用微信推送

## 执行流程

### 交易统计查询流程
1. 指定查询周期（1h/3h/6h/12h/24h）
2. 从 `trade_records.jsonl` 读取该周期内的交易记录
3. 计算总交易数、胜率、总盈亏、最大单笔盈亏
4. 返回格式化统计结果

### 对账流程
1. 从交易所 API 获取历史成交记录（`account_trade_list`）
2. 与本地 `trade_records.jsonl` 对比
3. 补充缺失的交易记录
4. 输出对账结果（补了多少条、是否有异常）

### 全场监控流程
1. 获取所有 USDT 永续合约实时价格
2. 与上一轮快照对比涨幅
3. 监测到 1h 涨幅 > 50% 的币种 → 微信推送预警
4. 保存当前价格快照作为下一轮对比基准

## 质量标准

- 交易记录必须使用交易所实际成交数据（`fills_agg`）
- 对账不删除已有记录，只补充缺失
- 统计计算基于成交明细的 `realized_pnl`，不估算
- 日志统一使用 `utils/logger.py` 的 `patch_print`
- 数据文件结构变更时需迁移兼容
- 所有K线数据基于币安实时API，不依赖历史CSV下载
