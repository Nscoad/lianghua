---
name: "data-utils"
description: 当用户要求"查看历史数据""读取信号""检查存储文件""分析盈亏""查看统计""看日志""查看交易记录""查对账单""运行对账"时必须使用。本 skill 管理所有数据持久化工具：JSON/SQLite 数据读写、K线趋势、平仓流水、统计、日志、微信通知、全场币种监控。
---

# 工具层 — 数据管理与工具函数

所有数据管理工具：SQLite交易流水表、价格快照数据库、K线趋势分析、平仓流水记录、日志系统、微信通知。

## 适用场景

- 用户要求"看看我的交易记录"、"查一下盈亏统计"
- 用户要求"检查数据文件"、"看下信号存哪里了"
- 用户要求"分析历史K线"、"下载历史数据"
- 用户要求"发个微信通知"、"推送消息到微信"
- 用户要求"监控全场币种"、"检测异常涨幅"
- 用户要求"对账"、"修复交易记录"
- 系统自动调用：快捞每1分钟、汇总报表每分钟检查（趋势采集已独立为 run_feed_collector.py 脚本）
- Web Dashboard 通过本层提供的 API 展示实时数据

## 安全约定

- 所有数据存储在 `data/` 目录下
- 微信通知使用 PushPlus 服务，token 从配置文件读取
- 不修改交易所原始数据，只做本地持久化
- 对账操作不会删除已有记录，只会补充缺失记录

## 数据文件一览

| 文件 | 用途 | 格式 |
|------|------|------|
| `data/trading.db` | 开平仓流水 + 日志 | SQLite |
| `data/market_monitor.db` | 价格快照（供快捞计算涨跌幅）| SQLite |
| `data/fast_trade_state.json` | 快捞仓位状态 | JSON |
| `data/market_analysis.json` | 市场分析结果（供前端看板）| JSON |
| `data/square_feeds.json` | 币安广场+X动态数据 | JSON |

## 推荐命令

```python
from utils.trade.stats import print_summary, calc_period_stats, reconcile_trades
from utils.trade.records import record_open, record_close
from utils.market.monitor import run_fast_monitor

# 查看交易统计
print_summary()

# 查看1小时统计
stats = calc_period_stats(hours=1)

# 对账
reconcile_trades()

# 快捞监测
run_fast_monitor()
```

## 文件位置及导出函数

### 核心工具

| 文件 | 主要函数 | 说明 |
|------|---------|------|
| `utils/db.py` | `init_db()`, `insert_trade_record()`, `get_trade_records()` | SQLite 建表/读写/迁移（含slippage/entry_mode字段） |
| `core/funding.py` | `query_funding_rate()`, `save_funding_record()` | 资金费率查询与持久化到 funding_records 表 |
| `utils/logger.py` | `patch_print()`, `flush_log()` | 日志系统（JSONL格式+时间戳+自动清理） |
| `utils/notifier.py` | `send_notification()`, `send_summary_report()` | PushPlus 微信通知 |

### 交易记录与统计

| 文件 | 主要函数 | 说明 |
|------|---------|------|
| `utils/trade/records.py` | `record_open()`, `record_close()` | 开平仓流水记录（含slippage参数） |
| `utils/trade/stats.py` | `calc_period_stats()`, `print_summary()`, `reconcile_trades()` | 交易统计 + 多币种对账 + 周期统计函数 |
| `utils/trade/analysis.py` | `save_summary_analysis()` | AI复盘分析存储到JSONL |

### 监控与市场数据

| 文件 | 主要函数 | 说明 |
|------|---------|------|
| `utils/market/monitor.py` | `run_fast_monitor()`, `get_all_usdt_symbols()` | 全场币种涨幅监控 + 快捞触发 |
| `utils/market/kline.py` | `check_kline_entry()`, `get_kline_levels()` | 实时K线趋势判断（MA3/MA6 + K线方向比例）|

## 关键功能说明

### 数据库表结构

**trade_records 表新增字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `slippage` | REAL DEFAULT 0 | 滑点（市价单成交价与下单前行情价的差值） |
| `entry_mode` | TEXT DEFAULT 'trend' | 入场模式（trend/volatility_override/sideways） |

**funding_records 表**（在 `core/funding.py` 中管理）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `time` | TEXT PRIMARY KEY | ISO格式时间 |
| `symbol` | TEXT NOT NULL | 交易对 |
| `side` | TEXT | LONG/SHORT |
| `funding_rate` | REAL | 资金费率 |
| `payment` | REAL | 实际支出（正=支出，负=收入） |
| `mark_price` | REAL | 结算标记价格 |
| `position_qty` | REAL | 持仓数量 |

### K线趋势（market/kline.py）

- `check_kline_entry(symbol, want_long)`：实时K线入场分析（MA3/MA6趋势判断）
- 数据源：币安实时API fapi/v1/klines（30秒缓存）
- `get_kline_levels(symbol, lookback=24)`：1h K线前高前低 + 盘整判断

### 交易统计（trade/stats.py）

- `calc_period_stats(hours)`：多周期（1h/3h/6h/12h/24h）交易统计
- `print_summary()`：盈亏汇总输出
- `reconcile_trades(since)`：交易所对账补记（扫描所有交易过的币种，启动时自动调用）

### 全场监控（market/monitor.py）

- `run_fast_monitor()`：每1分钟监测500+币种，15min涨>7.3%做多/跌>7.3%做空（含趋势过滤+冷却）
- `get_all_usdt_symbols()`：获取所有 USDT 永续合约实时价格

### 快捞交易（trade/fast_trader.py）

- `try_fast_open(symbol, price, prev_price)`：快速开多（10%余额，5x杠杆，15min涨>7.3%触发 + K线up趋势）
- `try_fast_short(symbol, price, prev_price)`：快速做空（10%余额，5x杠杆，15min跌>7.3%触发 + K线down趋势）
- `check_fast_position()`：检查快仓位止损/浮动锁仓/分批平仓

### 微信通知（notifier.py）

- `send_summary_report(period_label, stats, ai_analysis=None)`：微信汇总报表
- `send_notification(title, content)`：格式化微信通知

## 执行流程

### 交易统计查询流程

1. 指定查询周期（1h/3h/6h/12h/24h）
2. 从 `trading.db` SQLite 读取该周期内的交易记录
3. 计算总交易数、胜率、总盈亏、最大单笔盈亏
4. 返回格式化统计结果

### 对账流程

1. 从交易所 API 获取历史成交记录（`account_trade_list`）
2. 与本地 `trading.db` 对比
3. 补充缺失的交易记录
4. 输出对账结果（补了多少条、是否有异常）

### 快捞监控流程

1. 获取所有 USDT 永续合约实时价格
2. 与上一轮快照对比涨幅
3. 监测到 15min 涨跌幅 > 6% 的币种 → K线趋势过滤 → 开仓
4. 保存当前价格快照作为下一轮对比基准

## 质量标准

- 交易记录必须使用交易所实际成交数据（`fills_agg`）
- 对账不删除已有记录，只补充缺失
- 统计计算基于成交明细的 `realized_pnl`，不估算
- 日志统一使用 `utils/logger.py` 的 `patch_print`
- 数据文件结构变更时需迁移兼容
- 所有K线数据基于币安实时API，不依赖历史CSV下载
