# Lianghua — 币安U本位合约自动化交易系统

基于 **Binance U本位合约** 的全自动量化交易系统，核心策略为**快捞**（15分钟涨>7.3%做多/跌>7.3%做空 + 5秒持仓监控 + 动态锁仓止盈 + AI错误诊断 + 代理检测自动切换）。

## 系统架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                       调度器 (scheduler/)                             │
│                    6个并行线程                                        │
│  ┌───────┐ ┌───────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐          │
│  │持仓监控│ │快捞监测│ │资金费 │ │定时对 │ │汇总报 │ │代理检 │          │
│  │ 每5秒  │ │每2分钟 │ │ 率    │ │ 账    │ │ 表    │ │ 测    │          │
│  └───┬───┘ └───┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘          │
│      │         │        │        │        │        │               │
└──────┼─────────┼────────┼────────┼────────┼────────┼───────────────┘
       │         │        │        │        │        │
┌──────▼──┐ ┌────▼──┐ ┌──▼────┐ ┌─▼─────┐ ┌▼─────┐ ┌▼──────────┐
│  行动层  │ │信息层  │ │数据层  │ │代理层  │ │前端   │ │部署工具   │
│ core/   │ │ai/    │ │trading │ │proxy  │ │web   │ │scripts/   │
│ order   │ │analyze│ │.db    │ │manager│ │dash  │ │deploy/    │
│ queries │ │collect│ │JSONL  │ │Clash  │ │board │ │SSH隧道    │
│ client  │ │or/    │ │       │ │自动切  │ │Flask │ │Nginx      │
└─────────┘ └───────┘ └───────┘ └───────┘ └──────┘ └───────────┘
```

## 目录结构

```
lianghua/
├── scheduler/             调度器 — 6个并行线程
│   ├── __init__.py        入口：启动6个线程 + 交易所对账
│   ├── loops.py           并行循环实现
│   ├── state.py           汇总发送状态
│   └── conditions.py      前置条件检查
├── core/                  币安API封装
│   ├── client.py          客户端管理 + 时间同步 + 限流 + 代理切换
│   ├── queries.py         查询层：余额/价格/持仓/币种限制
│   ├── order.py           执行层：下单/平仓/止损（含分批拆单）
│   └── funding.py         资金费率追踪
├── ai/                    智能分析
│   └── analyzer.py        AI：下单错误诊断/周期复盘/广场X摘要
├── collector/             数据采集
│   ├── square.py          币安广场爬虫
│   ├── x_collector.py     X.com 采集
│   ├── trend_collector.py 趋势数据整合
│   ├── feed_collector.py  采集存储封装
│   └── feeds_db.py        采集数据管理（去重/过期清理）
├── utils/                 工具层
│   ├── db.py              数据库管理（SQLite交易流水/日志/复盘）
│   ├── logger.py          日志系统
│   ├── notifier.py        微信通知
│   ├── state.py           状态管理
│   ├── proxy_manager.py   Clash代理自动检测 & 节点切换
│   ├── trade/
│   │   ├── fast_trader.py 快捞策略（核心交易逻辑）
│   │   ├── records.py     开平仓流水
│   │   ├── stats.py       交易统计 + 对账补漏
│   │   └── analysis.py    AI复盘分析存储
│   └── market/
│       ├── monitor.py     全场币种快照 + 快捞监测
│       └── kline.py       实时K线趋势判断
├── web_dashboard/         前端看板
│   ├── app.py             Flask API
│   └── static/            HTML/CSS/JS
├── 启动交易系统.bat       一键启动菜单（双击运行）
├── scripts/               辅助脚本
│   ├── launch.ps1         启动菜单（被 bat 调用）
│   ├── tunnel.ps1         SSH反向隧道（本地→阿里云）
│   ├── deploy/            部署工具
│   │   ├── setup_ssh_key.py  SSH密钥配置
│   │   ├── setup_nginx.py    Nginx反向代理配置
│   │   ├── ssh_server.py     SSH远程命令执行
│   │   ├── upload_code.py    代码打包上传阿里云
│   │   └── ali_key.pem       SSH密钥
│   └── tools/             调试工具
│       ├── check_balance.py  查询账户余额
│       ├── check_symbol.py   查询币种交易限制
│       └── run_feed_collector.py 信息采集独立入口
├── strategy/              策略框架
├── config.py              全局配置
├── scheduler.py           调度入口
├── run_dashboard.py       看板启动
├── data/                  运行时数据（git忽略）
└── .gitignore
```

## 6个并行线程

| 线程 | 频率 | 职责 |
|------|------|------|
| **持仓监控** | 每5秒 | 检查已有快捞仓位的止损/锁仓 |
| **快捞监测** | 每2分钟 | 扫描500+币种，15min涨>7.3%做多/跌>7.3%做空 |
| **资金费率** | 每8小时 | 追踪持仓币种资金费率，记录支出/收入 |
| **定时对账** | 每30分钟 | 从交易所拉历史成交，补漏缺失记录 |
| **汇总报表** | 每分钟检查 | 到点发1h/3h/6h/12h/24h微信汇总 |
| **代理检测** | 每5分钟 | 检测Clash代理节点延迟，自动切换最优节点 |

## 快捞止盈策略

| 盈利到 | 锁仓线 | 说明 |
|:------:|:------:|:----:|
| < 10% | 不锁仓 | 利润太小，给空间 |
| +10%~+30% | +2%~+14% | 每多5%盈利，锁仓线上移2% |
| ≥ 30% | **固定5%价格回撤** | 转杠杆后25%保证金回撤，不再K线动态 |

## 智能特性

- **AI错误诊断**: 下单失败时调用DeepSeek分析错误原因并给出修复建议
- **Clash代理自动切换**: API连接连续失败 → 自动发现Clash节点 → 测速 → 切换到延迟最低节点
- **交易记录自动对账**: 启动时 + 每30分钟从交易所拉取历史成交，补漏缺失记录
- **时间同步**: 自动校准本地与币安服务器时间差，避免-1021时间戳错误

## 公网访问（阿里云部署）

系统通过SSH反向隧道将本地看板映射到阿里云服务器，公网可访问：

```
本地: Flask :5000  ←→  SSH隧道  ←→  阿里云 :5000  ←→  Nginx :80  ←→  公网
```

### 启动隧道

```powershell
.\scripts\tunnel.ps1
```

访问 [http://8.129.101.134](http://8.129.101.134) 即可查看看板。

## 启动

```bash
# 一键启动（菜单）
# 双击 启动交易系统.bat

# 生产模式
uv run python scheduler.py forever

# 单独启动看板
uv run python run_dashboard.py

# 信息采集
uv run python scripts/tools/run_feed_collector.py          # 一次采集+AI摘要
uv run python scripts/tools/run_feed_collector.py --loop   # 循环模式
```

## 配置 (`config.py`)

| 配置项 | 说明 |
|--------|------|
| `TESTNET_API_KEY` / `TESTNET_SECRET` | 测试网密钥 |
| `MAINNET_API_KEY` / `MAINNET_SECRET` | 实盘密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek AI Key |
| `PUSHPLUS_TOKEN` | 微信通知 Token |
| `USE_TESTNET` | True=测试网, False=实盘 |

## 微信消息推送

| 周期 | 时间 | 内容 |
|------|------|------|
| 1小时 | 每个整点 | 盈亏/多空比 |
| 3小时 | 每3h整点 | 盈亏/多空比 |
| 6小时 | 每6h整点 | 盈亏/多空比/原因分布 |
| 12小时 | 每12h整点 | 盈亏/多空比/币种明细 |
| 24小时 | 每天00:05 | 完整汇总 + AI复盘分析 |
