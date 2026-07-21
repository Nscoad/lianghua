---
name: "core-trader"
description: "行动层 — 封装币安U本位合约API（查余额、下单、持仓、杠杆、止损单）。当用户需要执行买卖、查持仓、查余额、设杠杆、设服务器止损等具体合约操作时调用。"
---

# 行动层 — core/trader.py

## 概述

币安 U本位合约 API 的执行封装，所有合约操作的最底层。所有上层模块（策略层、调度器）都依赖此模块与币安交互。

内置自动时间同步（处理 -1021 错误）：API 报错时自动调用 `w32tm /resync` 并重建客户端。

内置**全局 API 速率限制**（`_rate_limit()`）：相邻两次 API 调用至少间隔 200ms，避免触发交易所限频。

内置**5秒缓存**：`get_current_price()` 和 `get_position()` 在 5 秒内返回缓存结果，减少重复 API 调用。

## 文件位置

`core/trader.py`

## 导出函数

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `get_client()` | 初始化 API 客户端（带配置） | client 实例 |
| `check_balance()` | 查询 USDT 可用余额 | `float` |
| `check_all_balances()` | 打印全币种余额详情（含未实现盈亏） | `None` |
| `set_leverage(symbol, leverage)` | 设置合约杠杆倍数 | `data` 或 `None` |
| `get_current_price(symbol)` | 获取合约最新价格（**5秒缓存**，缓存命中时跳过 API 调用） | `float` 或 `None` |
| `place_market_order(symbol, side, quantity)` | 发送市价单，下单后自动查 trade_list 获取真实成交数据。失败时自动调 AI 分析原因（analyze_order_error） | `(order_data, fills_agg)` |
| `get_fills_agg(symbol, order_id)` | 查询某笔订单的真实成交明细（累计数量、加权均价、手续费、已实现盈亏），重试3次 | `dict{qty, avg_price, commission, realized_pnl}` |
| `place_stop_loss_order(symbol, side, quantity, entry_price, stop_loss_ratio=0.30)` | 设置服务器端止损单（STOP_MARKET），即使程序崩溃也生效 | `dict` 或 `None` |
| `close_position(symbol)` | 平掉指定交易对全部仓位，返回真实成交数据。失败时自动调 AI 分析原因 | `(order_data, fills_agg)` |
| `get_position(symbol)` | 查询持仓信息（含 entry_price, position_amt, mark_price, un_realized_profit；**5秒缓存**） | `dict` 或 `None` |

## 配置依赖

从 `config.py` 的 `get_futures_config()` 读取 API Key/Secret/URL，支持测试网和生产环境切换。

## 典型使用场景

```python
from core.trader import check_balance, get_current_price, place_market_order, get_position, place_stop_loss_order, get_fills_agg

# 查余额
balance = check_balance()

# 查价格
price = get_current_price("BANKUSDT")

# 开多（返回真实成交数据）
order_data, fills = place_market_order(symbol="BANKUSDT", side="BUY", quantity=1000)
print(f"成交: {fills['qty']} @ {fills['avg_price']}, 手续费: {fills['commission']} USDT")

# 设置服务器止损（跌30%保证金自动平仓）
place_stop_loss_order(symbol="BANKUSDT", side="SELL", quantity=1000, entry_price=price, stop_loss_ratio=0.30)

# 查持仓（含未实现盈亏）
pos = get_position("BANKUSDT")
print(pos["un_realized_profit"])  # 实时浮盈

# 平仓（返回真实成交数据，含已实现盈亏和手续费）
_, close_fills = close_position("BANKUSDT")
print(f"平仓: PnL={close_fills['realized_pnl']}, 手续费={close_fills['commission']}")

# 单独查询某笔订单的成交明细
fills = get_fills_agg("BANKUSDT", order_id=123456)
```

## 注意事项

- 使用 `USE_TESTNET` 控制测试网/实盘（`config.py`）
- 所有订单为市价单（MARKET），无限价单功能
- 采用单向持仓模式（One-way Mode）
- 数量按整数步长计算（合约要求）
- 时间戳错误（-1021）自动恢复：`w32tm /resync` + 重建客户端
- 测试网可能不支持 `STOP_MARKET`，会优雅降级提示
- 全局 API 速率限制（`_rate_limit()`）：所有 API 调用相邻间隔至少 200ms
- **5秒缓存**：`get_current_price()` 和 `get_position()` 使用内存缓存，5 秒内重复调用不发起 API 请求
