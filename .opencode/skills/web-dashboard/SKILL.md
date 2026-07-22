---
name: "web-dashboard"
description: "当用户要求"打开看板""查看实时看板""本地监控页面""网页看板""交易监控看板""打开网页"时必须使用。本 skill 启动本地 Flask 看板服务器（含 Cloudflare Tunnel 内网穿透），通过 web 页面实时展示保证金、仓位、风控状态、交易统计、周期分析和运行日志。"
---

# Web Dashboard — 本地交易看板

本地实时看板，基于 Flask + Cloudflare Tunnel，从本地数据库和交易所 API 实时获取数据，通过浏览器展示。

## 适用场景

- 用户要求"打开网页看板""查看实时数据""看监控页面"
- 用户要求"用浏览器查看交易状态""启动看板服务器"
- 用户要求"内网穿透""外网访问""手机查看"
- 用户在手机或另一台电脑上想看交易数据

## 安全约定

- 看板只 read，不 write，不会修改任何交易或风控状态
- Cloudflare Tunnel 随机生成地址，每次重启变化
- 穿透地址写入 `data/cloudflare_url.txt`，可随时读取

## 输入输出

输入：无（自动从本地数据源读取）

输出：

```
http://localhost:5000          — 本地访问
https://xxxx.trycloudflare.com — 外网穿透（每次重启变化）
```

数据源：

| 数据 | 来源 |
|------|------|
| 保证金余额 | 币安 API `check_balance()` |
| 当前仓位 | 币安 API `get_position()` + `fast_trade_state.json` |
| 风控状态 | `fast_trade_state.json`（锁仓线/冷却） |
| 交易总览 | `trading.db trade_records`（胜率/多空比/总盈亏） |
| 周期统计 | `calc_period_stats(1h/3h/6h/12h/24h)` |
| 运行日志 | `trading.db run_log`（最近 200 条） |

## 推荐命令

```bash
# 启动看板（含 Cloudflare 穿透）
uv run python run_dashboard.py

# 仅启动看板（无穿透）
uv run python -c "from web_dashboard.app import start_server; start_server()"
```

## 执行流程

1. **启动服务器**
   - 从 `web_dashboard/app.py` 初始化 Flask app
   - 所有 API 在 `/api/*` 路径下
   - 前端静态页面在 `/`

2. **Cloudflare 穿透**（可选）
   - `flask-cloudflared` 自动下载并启动 `cloudflared` 进程
   - 生成 `https://*.trycloudflare.com` 地址
   - 地址写入 `data/cloudflare_url.txt`

3. **提供 API**
   - `GET /api/balance` — 保证金余额
   - `GET /api/position` — 当前仓位 + 风控状态
   - `GET /api/logs` — 最近运行日志
   - `GET /api/stats` — 1h/3h/6h/12h/24h 周期统计
   - `GET /api/summary` — 交易总览（多空比/胜率/总盈亏）
   - `GET /api/signals` — 最近交易信号
   - `GET /api/system` — 系统运行时间

4. **前端看板**
   - 深色主题，每 5 秒自动刷新
   - 保证金、仓位、风控状态顶栏
   - 交易总览 5 卡片
   - 周期统计 5 标签切换
   - 仓位详情表格
   - 运行日志实时滚动（支持过滤）
   - 错误日志红色高亮

## 质量标准

- 所有 API 返回 JSON（错误时也返回 JSON，HTTP 200）
- 前端不报任何 JS 错误
- 穿透地址必须可外网访问
- 停止服务后自动关闭 cloudflared 进程
