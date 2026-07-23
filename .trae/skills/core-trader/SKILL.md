---
name: "core-trader"
description: "行动层 — 封装币安U本位合约API（查余额、下单、持仓、杠杆、止损单）。当用户需要执行买卖、查持仓、查余额、设杠杆、设服务器止损等具体合约操作时调用。"
---

# 行动层 — core/

## 概述

币安 U本位合约 API 的四层封装，所有合约操作的最底层。分四个文件：

1. **`client.py`** — 客户端管理 + 时间同步 + API限流 + 错误处理
2. **`queries.py`** — 查询层：余额/价格/持仓/成交明细/币种限制/实盘价格
3. **`funding.py`** — 资金费率查询 + 持久化到 `funding_records` 表
4. **`order.py`** — 执行层：下单/平仓/止损（含分批拆单+滑点追踪）

内置自动时间同步（处理 -1021 错误）；**全局 API 速率限制**（相邻调用间隔 ≥ 200ms）；**5秒缓存**（价格和持仓查询）。

## 文件位置

### client.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `get_client()` | 初始化 API 客户端（带配置） | client 实例 |
| `_rate_limit()` | 全局限流：相邻API调用至少200ms | `None` |
| `_handle_api_error(e, context)` | 时间戳错误(-1021)自动同步+重建客户端 | `True/None` |
| `_sync_system_time()` | 校准本地时间偏移 | `bool` |

### queries.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `check_balance()` | 查询 USDT 可用余额 | `float` |
| `check_all_balances()` | 打印全币种余额详情（含未实现盈亏） | `None` |
| `get_current_price(symbol)` | 获取合约最新价格（**5秒缓存**） | `float` 或 `None` |
| `get_real_price(symbol)` | 获取真实价格（测试网时拉实盘 API，实盘时复用 get_current_price），**5秒缓存** | `float` 或 `None` |
| `get_fills_agg(symbol, order_id)` | 查询某笔订单的真实成交明细（含滑点） | `dict{qty, avg_price, commission, realized_pnl, slippage}` |
| `get_position(symbol)` | 查询持仓信息（**5秒缓存**） | `dict` 或 `None` |
| `has_open_position()` | 检查是否有任何币种持仓 | `bool` |
| `_get_symbol_limits(symbol)` | 获取币种交易限制参数 | `dict` |

### funding.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `get_funding_fee_records(symbol=None, limit=100)` | 查询最近资金费率记录并持久化到 `funding_records` 表 | `list[dict]` |

查询币安 `/fapi/v1/income?incomeType=FUNDING_FEE`，返回资金费率历史记录，自动写入 SQLite 的 `funding_records` 表。

### order.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `set_leverage(symbol, leverage)` | 设置合约杠杆倍数 | `data` 或 `None` |
| `place_market_order(symbol, side, quantity)` | 发送市价单，下单前记录行情价，成交后计算滑点，失败自动调 AI 分析 | `(order_data, fills_agg)` — fills_agg 含 `slippage` 字段 |
| `place_stop_loss_order(symbol, side, quantity, entry_price, stop_loss_ratio=0.30)` | 设置服务器端止损单（STOP_MARKET） | `dict` 或 `None` |
| `close_position(symbol)` | 平仓（含分批+减量重试），失败调 AI 分析 | `(order_data, fills_agg)` — fills_agg 含 `slippage` 字段 |

## 配置依赖

从 `config.py` 的 `get_futures_config()` 读取 API Key/Secret/URL，支持测试网和生产环境切换。

## 典型使用场景

```python
from core.queries import check_balance, get_current_price, get_real_price, get_position, get_fills_agg
from core.order import place_market_order, place_stop_loss_order, close_position
from core.funding import get_funding_fee_records

# 查余额
balance = check_balance()

# 查价格
price = get_current_price("BANKUSDT")

# 查真实价格（测试网时从实盘 API 获取，避免深度失真）
real_price = get_real_price("BANKUSDT")

# 开多（返回真实成交数据，含滑点）
order_data, fills = place_market_order(symbol="BANKUSDT", side="BUY", quantity=1000)
print(f"成交: {fills['qty']} @ {fills['avg_price']}, 手续费: {fills['commission']} USDT, 滑点: {fills['slippage']}")

# 设置服务器止损（跌30%保证金自动平仓）
place_stop_loss_order(symbol="BANKUSDT", side="SELL", quantity=1000, entry_price=price, stop_loss_ratio=0.30)

# 查持仓（含未实现盈亏）
pos = get_position("BANKUSDT")
print(pos["un_realized_profit"])  # 实时浮盈

# 平仓（返回真实成交数据，含已实现盈亏、手续费和滑点）
_, close_fills = close_position("BANKUSDT")
print(f"平仓: PnL={close_fills['realized_pnl']}, 手续费={close_fills['commission']}, 滑点={close_fills['slippage']}")

# 单独查询某笔订单的成交明细（含滑点）
fills = get_fills_agg("BANKUSDT", order_id=123456)

# 查询资金费率记录
funding_records = get_funding_fee_records(symbol="BANKUSDT", limit=50)
```

## 注意事项

- 使用 `USE_TESTNET` 控制测试网/实盘（`config.py`）
- 所有订单为市价单（MARKET），无限价单功能
- 采用单向持仓模式（One-way Mode）
- 数量按整数步长计算（合约要求）
- 时间戳错误（-1021）自动恢复
- 测试网可能不支持 `STOP_MARKET`，会优雅降级提示
- 全局 API 速率限制：所有 API 调用相邻间隔至少 200ms
- **5秒缓存**：`get_current_price()` 和 `get_position()` 使用内存缓存
