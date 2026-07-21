---
name: "trade-strategy"
description: "交易策略层 — 自动交易执行 + 动态风险管理（止损/止盈减仓/追踪止损）+ 信号确认延迟 + 服务器止损。当用户需要调整策略参数、查看风险状态、检查策略逻辑时调用。"
---

# 交易策略层 — strategy/

## 概述

根据 AI 信号执行开平仓，同时内置完整的风险管理体系。这是系统的"执行大脑"。

## 交易纪律

- **A. 持仓中** → 只监控当前单子的止损/止盈，禁止开任何新单
- **B. 空仓时** → 开仓保证金 = 20% 可用余额，基于新余额重新计算
- **C. 冷却** → 上一单止损后进入冷却状态，需满足**双确认信号**才允许开仓，盈利一单后自动退出冷却

## 文件位置

| 文件 | 说明 |
|------|------|
| `strategy/auto_trader.py` | 交易执行核心（含AI信号确认延迟、K线趋势过滤、冷却双确认、交易所数量限制、服务器止损） |
| `strategy/risk_monitor.py` | 3秒高频风险监控（止损/止盈/追踪激活/追踪平仓） |
| `strategy/risk_manager.py` | 风险状态持久化（JSON，含冷却状态读写） |

## 导出函数

### auto_trader.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `run_auto_trade()` | 主入口：取最新信号 → 执行交易 | `dict` |
| `execute_signal(signal)` | 根据信号执行开平仓（含120s确认延迟 + K线趋势分析 + 横盘换币 + 冷却双确认） | `dict` |
| `get_symbol_limits(symbol)` | 查询交易所的LOT_SIZE/MARKET_LOT_SIZE限制 | `dict` |
| `calc_quantity_from_margin(price, margin, symbol)` | 按保证金计算合规数量 | `int` |
| `get_current_holding_symbol()` | 从风险状态获取当前持仓币种 | `str` 或 `None` |

### risk_monitor.py

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `check_risk_once(silent)` | 单次风险检查（3秒循环调用），止损后触发冷却 | `str` |
| `get_current_pnl_data(symbol)` | 获取持仓浮盈数据（供AI强制平仓判断） | `dict` |

### risk_manager.py

| 函数 | 说明 |
|------|------|
| `load_risk_state()` | 读取风险状态（含 `cooling` 标志） |
| `save_risk_state(state)` | 保存风险状态 |
| `reset_risk_state(symbol, margin)` | 开新仓时初始化，清除冷却 |
| `clear_risk_state()` | 平仓时清空 |
| `set_cooling()` | 止损后设置冷却状态 |
| `exit_cooling()` | 盈利一单后退出冷却状态 |
| `is_cooling()` | 检查是否在冷却中 |

### 空仓立即重新建仓
平仓（止损/止盈/追踪平仓）触发后，**scheduler.py** 的 `_try_re_entry()` 会立即执行一轮完整的 采集→AI分析→信号执行 流程，无需等待 15 分钟的下一次 AI 分析循环。

## 关键特性

### 信号确认延迟
开仓前等待120秒（2根1分钟K线），确认价格未反向波动超过3%才执行（5x杠杆下约为止损阈值的一半），避免AI追高/追低。

### 冷却双确认（取代1小时等待）
上一单止损后进入冷却状态。下一单开仓必须同时满足以下任一组合，达标才能开仓：

**A（必须）+ B 或 C（至少一个）：**
- **A**: 价格站上MA5 + 收盘突破前高（做多）/ 跌破MA5 + 收盘跌破前低（做空）
- **B**: RSI(14)>35 + MACD金叉（指标确认）
- **C**: 最后一根成交量 > 近10根均量（资金确认）

盈利一单（止盈/追踪平仓）后自动退出冷却。

### K线入场分析
价格确认通过后，执行K线趋势分析：
1. 查主币种最近24小时K线的 **MA6 vs MA20**，判断趋势方向（up/down/sideways）
2. 检查是否**放量突破**（范围比>60% + 量比>1.2 + 涨跌幅>0.3%）
3. 趋势突破 → 直接开仓
4. 横盘 → **等180秒**重查，仍横盘则尝试**候选币种**（从涨跌榜实时获取，不再硬编码）
5. 全部横盘 → 等待下一轮（15分钟）

### 动态候选币种
候选币列表从24h涨跌榜实时获取（`utils/market_screener.get_dynamic_candidates`），不再硬编码 BANKUSDT/ACEUSDT/KAITOUSDT/HOMEUSDT。

### 交易所数量限制
开仓前查询 `MARKET_LOT_SIZE` 和 `LOT_SIZE` 的 `max_qty`，自动截取上限，防止低价币超量下单。

### 服务器端止损
开仓后自动在币安服务器设置 `STOP_MARKET` 止损单（30%保证金），即使程序崩溃或断网也自动执行。
（测试网可能不支持，优雅降级）

## 风险管理策略

以 **余额 100u，开仓 20% = 20u 保证金，5x 杠杆** 为例：

| 条件 | 操作 | 示例 |
|------|------|------|
| **开仓** | 20% 余额作为保证金 | 余额100u → 开20u |
| **止损** | 亏损 ≥ 30% 当前保证金 = 6% 余额 | 亏6u → 全平 |
| **止盈减仓** | 盈利 ≥ 40% 初始保证金 = 8% 余额 | 赚8u → 减仓55%(减11u)，止损移至开仓价保本 |
| **追踪启动** | 剩余仓位盈利 ≥ 50% 剩余保证金 | 余9u，浮盈≥4.5u时激活 |
| **追踪平仓** | 浮盈从最高点回撤 ≥ 15% | 最高8u → 回撤至6.8u时全平 |

## 交易参数

在 `auto_trader.py` 头部可调整：

```python
LEVERAGE = 5                    # 杠杆倍数
MARGIN_RATIO = 0.2              # 开仓比例（20%余额）
DEFAULT_SYMBOL = "BANKUSDT"     # 回退符号（涨跌榜取不到时使用）
```

在 `risk_monitor.py` 头部可调整：

```python
STOP_LOSS_RATIO = -0.30         # 止损（30%保证金）
TAKE_PROFIT_RATIO = 0.40        # 止盈触发（40%保证金）
TP_REDUCE_RATIO = 0.55          # 止盈减仓比例（55%）
TRAILING_ACTIVATE_RATIO = 0.50  # 追踪激活（50%剩余保证金）
TRAILING_CLOSE_DRAWDOWN = 0.15  # 追踪平仓回撤（15%）
```

## 风险状态文件

`data/risk_state.json` — 存储当前持仓的风险管理状态：

```json
{
  "symbol": "BANKUSDT",
  "original_margin": 20.0,
  "current_margin": 9.0,
  "tp_done": true,
  "trailing_active": true,
  "highest_pnl": 4.5,
  "cooling": false
}
```
