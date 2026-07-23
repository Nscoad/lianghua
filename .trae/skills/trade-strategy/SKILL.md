---
name: "trade-strategy"
description: "交易策略层 — 快捞策略（15分钟涨>7.3%做多/跌>7.3%做空）+ K线趋势过滤 + 动态锁仓止盈（K线波动算回撤）。当用户需要调整策略参数、查看仓位状态、检查策略逻辑时调用。"
---

# 交易策略层 — utils/trade/fast_trader.py

## 概述

这是系统的唯一交易策略——**快捞**。每2分钟监测全场币种，捕捉15分钟内涨>7.3%或跌>7.3%的异常波动币种，小仓追涨杀跌，不扛单。

## 交易纪律

- **开仓方向**：涨>7.3%做多（追情绪），跌>7.3%做空（跟恐慌）
- **K线趋势过滤**：做多需要K线趋势向上（MA6>MA20），做空需要趋势向下（MA6<MA20）
- **不扛单**：动态锁仓止盈，利润回撤到锁仓线自动平
- **冷却**：平仓后进入30分钟冷却（`is_cooling(symbol, want_long=None)`），趋势匹配时自动提前解除（`_try_release_cooling()`），不再死等
- **入场模式**：开仓记录带 entry_mode 字段（trend/volatility_override/sideways），区分不同触发途径
- **滑点跟踪**：开仓/平仓记录记录实际 slippage，监控深度偏差
- **持仓监控循环**：5秒 position_loop 实时检查止损/锁仓（`get_real_price()` 代替 `get_current_price()`，避免测试网深度失真）
- **波动覆盖**：5分钟振幅 >9.3% 时波动率覆盖可绕过K线趋势过滤
- **每仓仓位**：10%总余额，5x杠杆

## 文件位置

`utils/trade/fast_trader.py`

## 导出函数

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `try_fast_open(symbol, price, prev_price)` | 尝试做多开仓（含K线趋势过滤、已持仓检查、仓位上限检查），记录 entry_mode 到 trade_records | `bool` |
| `try_fast_short(symbol, price, prev_price)` | 尝试做空开仓（同上），记录 entry_mode 到 trade_records | `bool` |
| `check_fast_position()` | 监控所有持仓：5秒 position_loop 更新浮盈、动态锁仓线、平仓检查（使用 `get_real_price()` 获取实盘价格） | `None` |

## 快捞参数

```python
FAST_LEVERAGE = 5           # 杠杆倍数
FAST_MARGIN_RATIO = 0.10    # 每仓10%总余额
FAST_SURGE_THRESHOLD = 0.073 # 15分钟涨幅>7.3%触发
FAST_LOOKBACK = 900         # 对比15分钟前价格
FAST_MIN_VOLUME = 500_000   # 最低成交额50万USDT
FAST_LOCK_FLOOR_INIT = 0.02 # 最低锁仓线2%
MAX_ACTIVE_POSITIONS = 3    # 最多同时持仓3个
FAST_COOLING_SEC = 1800     # 止损后冷却30分钟
```

## 动态锁仓策略

| 条件 | 锁仓计算 |
|------|---------|
| 利润 < 10% | 不锁仓（`profit_floor = None`） |
| 10% ~ 30% | 阶梯锁：每多5%利润，锁仓线上移2%（+10%→+2%, +15%→+4%, ...） |
| ≥ 30% | **K线动态回撤**：1h振幅 × 趋势系数(2.0/1.0) × 4，保底5%回撤空间 |

## 开仓流程

1. `get_all_usdt_symbols()` 获取所有USDT币种价格
2. 对比15分钟前价格，计算涨跌幅
3. 涨>7.3% → `try_fast_open()`：
   - 检查是否已持仓/到达上限/冷却中（`is_cooling(symbol, want_long=True)`，趋势匹配可提前解除）
   - 获取K线趋势，确认方向匹配——做多需up，做空需down；若5分钟振幅>9.3%则波动率覆盖可绕过趋势过滤
   - 计算数量 = 余额 × 10% × 杠杆 / 价格
   - 设杠杆 → 市价开仓 → 记录开仓流水（含 entry_mode 和 slippage 字段）→ 设置冷却
4. 跌>7.3% → `try_fast_short()`（同上，方向反过来）

## 平仓逻辑（`check_fast_position()` — 5秒 position_loop）

1. 遍历所有快捞持仓
2. 使用 `get_real_price()` 获取实盘价格计算浮盈率（含杠杆）
3. 更新最高盈利 → 计算动态锁仓线
4. 浮盈 <= 锁仓线 → 平仓（锁仓止盈），记录 slippage
5. 浮亏 <= -100%（保证金亏光）→ 强制平仓，记录 slippage
6. 平仓 → 记录平仓流水（含 slippage）→ 设置冷却
