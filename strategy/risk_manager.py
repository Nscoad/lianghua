"""
策略层 — 仓位风险管理状态持久化
"""
import os
import json

RISK_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "risk_state.json")


def _default_state() -> dict:
    return {
        "symbol": "",
        "original_margin": 0.0,
        "current_margin": 0.0,
        "tp_done": False,
        "cooling": False,
    }


def load_risk_state() -> dict:
    """读取风险管理状态"""
    if not os.path.exists(RISK_STATE_FILE):
        return _default_state()
    try:
        with open(RISK_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return _default_state()


def save_risk_state(state: dict):
    """保存风险管理状态"""
    os.makedirs(os.path.dirname(RISK_STATE_FILE), exist_ok=True)
    with open(RISK_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def reset_risk_state(symbol: str, margin: float):
    """重置状态（开新仓时调用，清除冷却）"""
    state = _default_state()
    state.update({
        "symbol": symbol,
        "original_margin": margin,
        "current_margin": margin,
    })
    save_risk_state(state)
    return state


def clear_risk_state():
    """清空状态（平仓时调用，保留冷却标志）"""
    state = _default_state()
    existing = load_risk_state()
    if existing.get("cooling"):
        state["cooling"] = True
    save_risk_state(state)


def set_cooling():
    """设置冷却状态（止损后调用）"""
    state = load_risk_state()
    state["cooling"] = True
    save_risk_state(state)
    print("[冷却] 进入冷却状态 — 下一单需双确认信号才能开仓")


def exit_cooling():
    """退出冷却状态（盈利一单后调用）"""
    state = load_risk_state()
    if state.get("cooling"):
        state["cooling"] = False
        save_risk_state(state)
        print("[冷却] 退出冷却状态 — 恢复正常交易")


def is_cooling() -> bool:
    """检查当前是否在冷却状态"""
    state = load_risk_state()
    return state.get("cooling", False)
