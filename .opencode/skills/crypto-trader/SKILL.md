---
name: "crypto-trader"
description: 当用户询问"交易系统""量化投资""加密货币自动交易""系统概览""交易机器人""自动化交易""启动系统""运行交易"时必须使用。本 skill 是 AI 驱动的币安 U本位合约自动化交易系统，具有快捞策略 + 趋势采集 + AI摘要 + 微信汇总报表功能。
---

# AI 加密货币合约交易系统

全自动 Binance U本位合约量化交易系统，基于快捞策略（追涨杀跌），配合币安广场 + X.com 趋势采集与 AI 摘要，定时微信汇总报表。包含 3 个并行循环 + 1 个 Web 看板。

## 适用场景

- 用户要求"启动交易系统"、"运行机器人"
- 用户要求"看看系统在干嘛"、"系统状态"
- 用户要求"了解这个交易系统"、"系统整体概览"
- 用户询问"量化交易"、"自动交易"、"交易机器人"等关键词
- 用户需要管理系统的启动/停止/状态查看

## 安全约定

- 使用币安 U本位合约，5x 杠杆
- 快捞止损 -1.5%（保证金比例），避免大幅亏损
- 止损后自动进入冷却期（默认15分钟，大亏损>20U延长至60分钟）
- 所有 API Key 从 `config.py` 读取，不暴露在任何文件中
- 系统启动时自动执行对账，确保交易记录完整

## 系统架构

```
┌───────────────────────────────────────────────────────────────┐
│                   3个并行循环（scheduler/）                      │
├──────────────────┬─────────────────────┬─────────────────────┤
│ 快捞             │ 趋势采集             │ 汇总报表             │
│ 每2分钟          │ 每30分钟             │ 每分钟检查           │
│ 监测500+币种      │ 采集广场热门+X.com   │ 到点发微信汇总       │
│ 15min涨>6%做多   │ AI摘要→微信通知      │ 1h/3h/6h/12h/24h   │
│ 15min跌>6%做空   │                     │                    │
└──────────────────┴─────────────────────┴─────────────────────┘
```

## 推荐命令

```bash
# 生产模式（3循环并行）
uv run python scheduler.py forever

# 单轮执行
uv run python scheduler.py

# 查看交易统计
uv run python -c "from utils.trade.stats import print_summary; print_summary()"
```

## 3个并行循环

| 循环 | 频率 | 职责 | 有持仓时 | 空仓时 |
|------|------|------|---------|--------|
| **快捞监控循环** | 每2分钟 | 扫描500+币种，15min涨>6%做多 / 跌>6%做空（趋势过滤+冷却），浮动锁仓让利润奔跑 | 仅检查持仓风控 | 运行 |
| **趋势采集循环** | 每30分钟 | 采集广场热门 + X.com 趋势，AI摘要后发微信通知 | 运行 | 运行 |
| **汇总报表循环** | 每分钟检查 | 到点发送 1h/3h/6h/12h/24h 微信汇总（含 AI 复盘分析） | 运行 | 运行 |

## 技能层级

| 技能 | 对应文件 | 层次 | 职责 |
|------|---------|------|------|
| core-trader | `core/client.py` + `core/queries.py` + `core/order.py` | 行动层 | 币安API执行层（查余额/下单/查持仓/设止损） |
| feed-collector | `collector/square.py`, `feed_collector.py`, `trend_collector.py`, `x_collector.py` | 采集层 | 币安广场 + X.com 数据爬取 |
| ai-analyzer | `ai/analyzer.py` | AI决策层 | 下单失败分析 / 周期复盘分析 / 趋势动态AI摘要 |
| trade-strategy | `utils/fast_trader.py` | 策略层 | 快捞策略执行与风控（仅快捞） |
| data-utils | `utils/db.py`, `utils/logger.py`, `utils/notifier.py`, `utils/trade/`, `utils/market/` | 工具层 | 数据/统计/监控/通知 |
| **web-dashboard** | `web_dashboard/app.py` | **看板层** | 本地Web看板 + Cloudflare穿透 |

## 调度器架构

```
scheduler/
├── __init__.py      # 入口：run_forever(), run_once() + 常量
├── loops.py         # 3个并行循环线程函数
├── state.py         # 共享状态（锁、计数器、持久化）
└── conditions.py    # 前置条件检查 + 系统状态打印
```

## 启动流程

1. **前置检查**：API密钥配置、Chrome调试模式、网络连接
2. **数据库初始化**：创建 `trading.db` 等数据文件
3. **交易对账**：自动从交易所拉取历史成交记录，补全本地记录
4. **启动3个并行线程**：分别在后台运行
5. **状态打印**：打印系统启动状态和各循环配置
6. **等待 Ctrl+C**：保持运行，各循环按各自频率执行

## 质量标准

- 快捞基于规则执行（趋势过滤 + 浮动锁仓），不依赖 AI 信号
- 持仓中禁止同币种开新单
- 止损后必须进入冷却期
- 汇总报表按时发送，不重复不遗漏
- 异常发生时记录日志并打印错误栈
- 启动时自动对账，保证交易记录完整

## 测试

```bash
# 单轮执行（不启动循环，只跑一次分析和交易）
uv run python scheduler.py

# 语法检查
python -m py_compile scheduler/__init__.py scheduler/loops.py scheduler/state.py
```

## Web Dashboard（可选）

独立于交易系统的本地看板，通过浏览器实时监控：

```bash
# 启动看板（含 Cloudflare 外网穿透）
uv run python run_dashboard.py
```

| 功能 | 地址 |
|------|------|
| 本地 | `http://localhost:5000` |
| 外网 | `data/cloudflare_url.txt` 中的 `*.trycloudflare.com` 地址 |

看板只读，不影响交易系统。详见 `web-dashboard` skill。
