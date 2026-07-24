---
name: "master-trader"
description: "交易总调度引擎 — 通过 scheduler 编排 3 个并行循环（快捞/趋势采集/汇总报表），协调各 skill 子模块的自动执行与数据流转。"
---

# Master Trader — 调度器总编排

## 职责

通过 `scheduler/` 调度器编排所有子模块 skill 的并行执行，各循环独立线程运行，共享数据库和状态。

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                     scheduler/（调度器）                           │
├──────────────────┬──────────────────────┬───────────────────────┤
│ 快捞循环(2min)   │ 趋势采集循环(30min)   │ 汇总报表循环(60s检查)  │
│                  │                      │                       │
│ market/monitor   │ trend_collector      │ trade/stats           │
│  → run_fast_     │  → collect_trends   │  → calc_period_stats  │
│    monitor()     │    (广场热门+X.com)  │  → analyze_summary_   │
│  → trade/fast_   │  → run_feed_summary │    stats (AI分析)     │
│    trader        │    (AI摘要→微信)     │  → send_summary_      │
│  (开仓/风控)     │                      │    report (微信)      │
└──────────────────┴──────────────────────┴───────────────────────┘
         │                    │                       │
         ▼                    ▼                       ▼
    core-trader          feed-collector          data-utils
    (币安API)             (数据采集)              (数据/统计/通知)
```

## 3个并行循环

| 循环 | 频率 | 线程名 | 职责 |
|------|------|--------|------|
| **快捞循环** | 每1分钟 | Fast-Trade | `market/monitor.py:run_fast_monitor()` → 监测500+币种涨跌>7.3% → `trade/fast_trader.py:try_fast_open/short` 开仓 → `check_fast_position()` 持仓风控 |
| **趋势采集循环** | 每30分钟 | Trend-Collector | `collect_trends()` 采集广场热门+X.com → `run_feed_summary()` AI摘要 → PushPlus 微信通知 |
| **汇总报表循环** | 每60秒检查 | Summary-Report | 到点（1h/3h/6h/12h/24h）→ `calc_period_stats()` → `analyze_summary_stats()` AI复盘 → `send_summary_report()` 微信推送 |

## 子模块调用关系

| 步骤 | 调用的 skill | 对应代码模块 |
|------|-------------|-------------|
| 快捞监测 | trade-strategy | `utils/market/monitor.py` → `utils/trade/fast_trader.py` |
| 快捞开仓/风控 | core-trader | `core/order.py:place_market_order()` + `core/queries.py:get_position()` |
| 趋势采集 | feed-collector | `collector/trend_collector.py`, `collector/square.py`, `collector/x_collector.py` |
| AI摘要 | ai-analyzer | `ai/analyzer.py:run_feed_summary()` |
| 交易统计 | data-utils | `utils/trade/stats.py:calc_period_stats()` |
| AI复盘 | ai-analyzer | `ai/analyzer.py:analyze_summary_stats()` |
| 微信通知 | data-utils | `utils/notifier.py:send_summary_report()` |

## 启动流程

```
scheduler/__init__.py:run_forever()
  │
  ├─ 1. init_db()                   创建 SQLite
  ├─ 2. patch_print()               统一日志
  ├─ 3. check_prerequisites()       检查API/Chrome/网络
  ├─ 4. reconcile_trades()          启动对账
  ├─ 5. 启动3个线程（daemon=True）
  │    ├─ fast_loop        快捞
  │    ├─ trend_loop       趋势采集
  │    └─ summary_loop     汇总报表
  └─ 6. print_status()     打印状态
```

## 调度器文件结构

```
scheduler/
├── __init__.py      # run_forever() / run_once() 入口
│                    # MONITOR_INTERVAL=1800, FAST_MONITOR_INTERVAL=60
├── loops.py         # 3个循环线程函数
│   ├─ fast_loop()         快捞（1分钟）
│   ├─ trend_loop()        趋势采集（30分钟）
│   └─ summary_loop()      汇总报表（60秒检查）
├── state.py         # 共享状态（锁、计数器、持久化）
└── conditions.py    # 前置条件检查 + 系统状态打印
```

## 执行示例

```
[调度器] 启动 3 个并行循环
  → 快捞监控循环: 每 2 分钟
  → 趋势采集循环: 每 30 分钟
  → 汇总报表循环: 每 60 秒检查

[快捞循环] 第1轮
  → run_fast_monitor()
  → 检查持仓风控：无持仓
  → 扫描500+币种：PROMUSDT 15min涨+8.2% > 6%
  → K线趋势up → 冷却检查通过 → 做多开仓
  → 成交：100 PROMUSDT @ 0.85 USDT

[趋势采集循环] 第1轮
  → collect_trends()：采集10条广场热门 + 10条X.com
  → run_feed_summary()：AI摘要→微信通知
  → 摘要：市场普遍看多BTC，PROMUSDT社区讨论热度上升

[汇总报表循环] 到整点
  → calc_period_stats(1) → 近1h +12.50 USDT
  → analyze_summary_stats() → 输出分析
  → send_summary_report() → 微信推送
```
