---
name: "core-trader"
description: 当用户要求"查余额""查持仓""下单""买卖""开仓""平仓""设杠杆""设止损""看账户""执行交易"等具体合约操作时必须使用。本 skill 封装币安 U本位合约 API，提供查余额、下单、持仓查询、杠杆设置、服务器止损等底层合约操作。
---

# 行动层 — 币安 U本位合约 API

对接币安 U本位合约 API 的执行封装，所有合约操作的最底层。包含全局速率限制（200ms 间隔）和自动时间同步。

## 适用场景

- 用户要求"查一下账户有多少 USDT"、"看看余额"
- 用户要求"买入 100 个 XXX"、"开多"、"做空 XXX"
- 用户要求"看看我的持仓"、"现在有什么仓位"
- 用户要求"设 5 倍杠杆"、"把杠杆调到 10 倍"
- 用户要求"设止损"、"给我设个服务器止损"
- 用户要求"平仓"、"全平了"
- 用户要求"现在 XXX 什么价格"

## 安全约定

- API Key 从配置文件读取（`config.py`），SKILL.md 不写入任何密钥
- `USE_TESTNET` 控制测试网/实盘（config.py），生产环境务必确认
- 所有订单为市价单，单向持仓模式
- 内置全局 API 速率限制：相邻 API 调用间隔至少 200ms
- 内置自动时间同步处理 -1021 错误
- 测试网可能不支持 STOP_MARKET，会优雅降级

## 输入输出

输入：用户的口语化指令（查余额/查持仓/下单/平仓/设杠杆/设止损）

输出：调用对应函数返回中文结果，失败时自动调 AI 分析原因

## 推荐命令

```python
from core.trader import check_balance, get_current_price, place_market_order, get_position, place_stop_loss_order

# 查余额
balance = check_balance()

# 查价格
price = get_current_price("BANKUSDT")

# 开仓
order_data, fills = place_market_order(symbol="BANKUSDT", side="BUY", quantity=1000)

# 设止损
place_stop_loss_order(symbol="BANKUSDT", side="SELL", quantity=1000, entry_price=price, stop_loss_ratio=0.30)

# 查持仓
pos = get_position("BANKUSDT")
```

## 导出函数

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `get_client()` | 初始化 API 客户端（带配置） | client 实例 |
| `check_balance()` | 查询 USDT 可用余额 | `float` |
| `check_all_balances()` | 打印全币种余额详情（含未实现盈亏） | `None` |
| `set_leverage(symbol, leverage)` | 设置合约杠杆倍数 | `data` 或 `None` |
| `get_current_price(symbol)` | 获取合约最新价格（**5秒缓存**） | `float` 或 `None` |
| `place_market_order(symbol, side, quantity)` | 发送市价单，失败时自动调 AI 分析原因 | `(order_data, fills_agg)` |
| `get_fills_agg(symbol, order_id)` | 查询某笔订单的真实成交明细 | `dict{qty, avg_price, commission, realized_pnl}` |
| `place_stop_loss_order(symbol, side, quantity, entry_price, stop_loss_ratio)` | 设置服务器端止损单（STOP_MARKET） | `dict` 或 `None` |
| `close_position(symbol)` | 平掉指定交易对全部仓位 | `(order_data, fills_agg)` |
| `get_position(symbol)` | 查询持仓信息（5秒缓存） | `dict` 或 `None` |
| `has_open_position()` | 是否有任何未平仓位 | `bool` |
| `get_open_position_symbol()` | 获取有持仓的交易对 | `str` 或 `None` |

## 执行流程

1. **解析用户意图**：从用户指令中识别操作类型（余额/持仓/下单/平仓/杠杆/止损）
2. **调用对应函数**：根据操作类型调用 core/trader.py 中的函数
3. **成功返回**：将结果格式化为中文输出展示给用户
4. **失败处理**：如果 API 调用失败，自动调用 `analyze_order_error` 让 AI 分析原因并返回建议

## 质量标准

- 余额和价格数据使用 5 秒缓存，避免频繁调用 API
- 下单失败时必须分析原因（余额不足/价格波动/网络问题等）
- 设置止损时确认止损比例合理（默认 30%-40% 保证金）
- 查询持仓时返回完整信息（方向/数量/开仓价/浮盈）

## 依赖

- `binance-futures-connector` 或 `python-binance`
- `config.py` 中配置 API Key/Secret 和杠杆参数
