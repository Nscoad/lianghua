# Lianghua — 币安U本位合约自动化交易系统

基于 **Binance U本位合约** 的全自动量化交易系统，核心策略为**快捞**（15分钟涨>7.3%做多/跌>7.3%做空 + 5秒持仓监控 + 动态锁仓止盈 + 滑点/资金费率追踪）。

## 系统架构（4层）

```
┌─────────────────────────────────────────────────────────────────┐
│                        调度器 (scheduler/)                        │
│             3个并行循环                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐    │
│  │  快捞循环      │ │ 趋势采集循环   │ │ 汇总报表循环           │    │
│  │  每2分钟       │ │ 每30分钟      │ │ 每小时/3h/6h/12h/24h  │    │
│  └──────┬───────┘ └──────┬───────┘ └──────────┬───────────┘    │
│         │                │                    │                 │
└─────────┼────────────────┼────────────────────┼─────────────────┘
          │                │                    │
┌─────────▼────┐ ┌─────────▼────┐ ┌────────────▼──────────┐
│  行动层       │ │  信息层       │ │  数据层                │
│  utils/trade │ │  market/     │ │  trading.db            │
│  /fast_trader│ │  monitor     │ │  market_monitor.db     │
│  core/       │ │  collector/  │ │  square_feeds.json      │
│  client      │ │  ai/         │ │                        │
│  queries     │ │  analyzer    │ │                        │
│  order       │ │              │ │                        │
└──────────────┘ └──────────────┘ └────────────────────────┘
                                   │
                           ┌───────▼────────┐
                           │   前端网页       │
                           │ web_dashboard/ │
                           └────────────────┘
```

## 目录结构

```
lianghua/
├── scheduler/          调度器 — 循环启动
│   ├── __init__.py     入口
│   ├── loops.py        并行线程
│   ├── state.py        汇总发送状态
│   └── conditions.py   前置条件检查
├── core/
│   ├── client.py       客户端管理 + 时间同步 + 限流
│   ├── queries.py      查询层：余额/价格/持仓/币种限制
│   ├── order.py        执行层：下单/平仓/止损（含分批拆单）
│   └── funding.py      资金费率追踪
├── ai/
│   └── analyzer.py     AI分析：下单错误诊断/周期复盘/广场X摘要
├── collector/
│   ├── square.py       币安广场爬虫
│   ├── x_collector.py  X.com 采集
│   ├── trend_collector.py  趋势数据整合
│   ├── feed_collector.py   采集存储封装
│   └── feeds_db.py     采集数据管理（去重/过期清理）
├── utils/
│   ├── db.py             数据库管理
│   ├── logger.py         日志系统
│   ├── notifier.py       微信通知
│   ├── trade/
│   │   ├── fast_trader.py  快捞策略（核心交易逻辑）
│   │   ├── records.py      开平仓流水
│   │   ├── stats.py        交易统计 + 对账
│   │   └── analysis.py     AI复盘分析存储
│   └── market/
│       ├── monitor.py      全场币种快照 + 快捞监测
│       └── kline.py        实时K线趋势判断
├── web_dashboard/      前端看板
│   ├── app.py          Flask API
│   └── static/         HTML/CSS/JS
├── config.py           全局配置
├── scheduler.py        调度入口
├── run_feed_collector.py  信息采集独立入口
├── data/               运行时数据
│   ├── trading.db      交易记录+日志
│   ├── market_monitor.db 价格快照
│   ├── market_analysis.json 市场分析结果
│   ├── fast_trade_state.json 快捞状态
│   ├── square_feeds.json 广场+X动态
│   └── summary_sent_state.json 汇总发送状态
└── .trae/skills/       技能定义
```

## 3个并行循环

趋势采集循环已独立为 `run_feed_collector.py` 脚本，scheduler 现在只有：

| 循环 | 频率 | 职责 |
|------|------|------|
| **持仓监控循环** | 每5秒 | 检查已有快捞仓位的止损/锁仓 |
| **快捞监测循环** | 每2分钟 | 扫描500+币种，15min涨>7.3%做多/跌>7.3%做空 |
| **汇总报表循环** | 每分钟检查 | 到点发1h/3h/6h/12h/24h微信汇总 |

## 快捞止盈策略

| 盈利到 | 锁仓线 | 说明 |
|:------:|:------:|:----:|
| < 10% | 不锁仓 | 利润太小，给空间 |
| +10%~+30% | +2%~+14% | 每多5%盈利，锁仓线上移2% |
| ≥ 30% | **固定5%价格回撤** | 转杠杆后25%保证金回撤，不再K线动态 |

## 微信消息

| 周期 | 时间 | 内容 |
|------|------|------|
| 1小时 | 每个整点 | 盈亏/多空比 |
| 3小时 | 每3h整点 | 盈亏/多空比 |
| 6小时 | 每6h整点 | 盈亏/多空比/原因分布 |
| 12小时 | 每12h整点 | 盈亏/多空比/币种明细 |
| 24小时 | 每天00:05 | 完整汇总 + AI复盘分析 |

## 启动

```bash
# 生产模式
uv run python scheduler.py forever

# 看板
uv run python run_dashboard.py

# 信息采集（独立运行）
uv run python run_feed_collector.py          # 一次采集+AI摘要
uv run python run_feed_collector.py --loop   # 循环模式
```

## 配置 (`config.py`)

| 配置项 | 说明 |
|--------|------|
| `TESTNET_API_KEY` / `TESTNET_SECRET` | 测试网密钥 |
| `MAINNET_API_KEY` / `MAINNET_SECRET` | 实盘密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek AI Key |
| `PUSHPLUS_TOKEN` | 微信通知 Token |
| `USE_TESTNET` | True=测试网, False=实盘 |
