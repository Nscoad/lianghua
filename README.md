# Lianghua — 币安U本位合约自动化交易系统

基于 **Binance U本位合约** 的全自动量化交易系统，通过快捞（涨>6%做多/跌>6%做空）+ 1:3盈亏比风险监控执行自动交易。

## 系统架构

```
             调度器 (scheduler/) — 5个并行循环
                                     
   快捞(2min)      风险监控(1.5s)    汇总报表(1min)    
   涨>6%做多        止损15%保证金     微信推送 1h/3h/   
   跌>6%做空        止盈45%保证金     6h/12h/24h       
   浮动锁仓止盈     保本止损                
                    防耗散/趋势反转           
                                     
          全场监控(1h)      趋势采集(15min)         
          500+币异常涨幅   广场热门 + X.com        
                                     
              ┌─────────┴─────────┐
              │ 策略层 (strategy/) │
              │ risk_monitor:      │
              │  止损/1:3止盈/保本  │
              │ risk_manager:      │
              │  状态持久化/冷却    │
              │ fast_trader:       │
              │  情绪币追涨杀跌    │
              └─────────┬─────────┘
                        │
              ┌─────────┴─────────┐
              │ 行动层 (core/)    │
              │ 币安U本位合约API   │
              │ 下单/持仓/余额     │
              └───────────────────┘
```

## 目录结构

```
lianghua/
├── scheduler/         调度器
│   ├── __init__.py    入口 — 5个循环启动
│   ├── loops.py       5个并行循环线程
│   ├── state.py       共享状态（计数器）
│   └── conditions.py  前置条件检查 + 状态打印
├── core/trader.py     行动层 — 币安合约API
├── ai/
│   └── analyzer.py    AI开仓分析 + 周期复盘分析
├── collector/
│   ├── square.py      币安广场爬虫
│   ├── x_collector.py X.com 首页采集
│   ├── trend_collector.py 趋势数据整合
│   └── feed_collector.py  采集存储封装
├── strategy/
│   ├── risk_monitor.py   1.5秒风控（止损/1:3止盈/保本/防耗散/趋势反转）
│   ├── risk_manager.py   风险状态持久化（含冷却标志）
│   └── auto_trader.py    主仓交易执行（备用，未启用）
├── utils/
│   ├── fast_trader.py    快捞交易（独立小仓，浮动锁仓止盈）
│   ├── market_monitor.py 全场币种监控 + 快捞监测
│   ├── market_screener.py 24h涨跌榜 + K线阶段分析
│   ├── historical_data.py 实时K线趋势判断
│   ├── trade_records.py  开平仓流水记录
│   ├── trade_stats.py    交易统计 + 对账
│   ├── trade_analysis.py AI复盘分析存储
│   ├── data_manager.py   JSON数据管理
│   ├── notifier.py       微信定时汇总（含余额变化）
│   ├── db.py             数据库管理
│   ├── logger.py         日志系统
│   └── trader_orch.py    汇总报表协调
├── config.py            全局配置
├── scheduler.py         调度入口
├── data/                运行时数据
│   ├── trading.db       交易记录+日志
│   ├── risk_state.json  风控状态
│   ├── square_feeds.json 广场+趋势动态
│   ├── summary_sent_state.json 汇总发送状态
│   └── ...
└── .opencode/skills/    技能定义
```

## 5个并行循环

| 循环 | 频率 | 职责 |
|------|------|------|
| **快捞** | 每2分钟 | 扫描500+币种，15min涨>6%做多/跌>6%做空，小仓追涨杀跌 |
| **风险监控** | 每1.5秒 | 止损15%保证金 / 1:3盈亏比止盈45% / 保本止损 / 防耗散 / 趋势反转 |
| **汇总报表** | 每分钟检查 | 到点发送 1h/3h/6h/12h/24h 微信汇总 |
| **全场监控** | 每1小时 | 检测500+币种1h涨幅>50%时微信预警 |
| **趋势采集** | 每15分钟 | 采集币安广场热门 + X.com 首页推文 |

## 主仓止盈策略（1:3盈亏比）

| 阶段 | 触发条件 | 操作 |
|------|---------|------|
| **初始止损** | 亏损 ≥ 15% 保证金（≈价格反3%） | 全平，进入冷却 |
| **TP1 首轮止盈** | 浮盈 ≥ 45% 保证金（≈价格正9%，3×止损） | 平50%，止损移至保本 |
| **保本止损** | 价格回到开仓价 | 全平（盈亏比保底 1:1.5） |
| **防耗散** | 3根1hK线无方向 / 盘整区 | 全平（不浪费时间） |
| **趋势反转** | K线趋势与持仓相反 | 全平（不逆势） |
| **趋势延续** | 方向正确，无以上条件 | 持有吃大行情 |

## 快捞止盈策略（浮动锁仓）

| 盈利到 | 锁仓线 | 说明 |
|:------:|:------:|:----:|
| +10% | +2% | 回撤到此就平，保底2%利润 |
| +15% | +4% | 每多5%盈利，锁仓线上移2% |
| +20% | +6% | 越涨容错空间越大 |
| ... | ... | 以此类推 |

## 微信汇总报表

| 周期 | 时间 | 内容 |
|------|------|------|
| 1小时 | 每个整点 | 期初/当前余额、盈亏、多空比 |
| 3小时 | 每3h整点 | 期初/当前余额、盈亏、多空比 |
| 6小时 | 每6h整点 | 余额变化、盈亏、多空比、原因分布 |
| 12小时 | 每12h整点 | 余额变化、盈亏、多空比、币种明细 |
| 24小时 | 每天00:05 | 完整汇总 + AI复盘分析 |

## 启动

```bash
# 生产模式（5循环并行）
uv run python scheduler.py forever

# 单轮执行
uv run python scheduler.py

# 查看统计
uv run python -c "from utils.trade_stats import print_summary; print_summary()"
```

## 配置 (`config.py`)

| 配置项 | 说明 |
|--------|------|
| `TESTNET_API_KEY` / `TESTNET_SECRET` | 测试网密钥 |
| `MAINNET_API_KEY` / `MAINNET_SECRET` | 实盘密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek AI Key |
| `PUSHPLUS_TOKEN` | 微信通知 Token |
| `USE_TESTNET` | True=测试网, False=实盘 |
