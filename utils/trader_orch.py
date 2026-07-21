"""
交易总调度引擎 — 动态决策用广场还是K线 + 复盘写入DB
"""
from datetime import datetime


# ==================== 动态数据源决策 ====================

def decide_data_source() -> dict:
    """
    动态判断本轮用广场动态还是纯K线，返回决策详情。
    
    规则：
      - Chrome在线 + 过去1h有≥3条新鲜动态 → 广场+K线双源
      - Chrome在线 + 动态不足 → 纯K线（广场辅助）
      - Chrome离线 → 纯K线
      - 历史复盘显示最近10笔亏损率>60% → 切换数据源
    """
    result = {
        "use_square": False,
        "use_kline": True,
        "reason": "",
        "confidence_boost": 0,
        "square_available": False,
        "fresh_feeds": 0,
    }

    # 检查 Chrome 和广场动态
    try:
        from collector.square import ensure_chrome_debug
        chrome_ok = ensure_chrome_debug()
        result["square_available"] = chrome_ok

        if chrome_ok:
            from utils.data_manager import get_active_feed_count
            feed_count = get_active_feed_count(hours=1)
            result["fresh_feeds"] = feed_count
            if feed_count >= 3:
                result["use_square"] = True
                result["reason"] = f"广场动态充足 ({feed_count}条)，双源分析"
                result["confidence_boost"] = 5
            else:
                result["reason"] = f"广场动态不足 ({feed_count}条)，纯K线分析"
        else:
            result["reason"] = "Chrome不可用，纯K线分析"
    except Exception as e:
        result["reason"] = f"广场采集异常: {e}，纯K线分析"

    # 历史复盘影响
    from utils.db import get_recent_reviews
    recent = get_recent_reviews(10)
    if len(recent) >= 3:
        recent_losses = sum(1 for r in recent if r.get("total_pnl", 0) < 0)
        loss_rate = recent_losses / len(recent)
        if loss_rate > 0.6:
            result["confidence_boost"] -= 10
            result["reason"] += f" | 近期{recent_losses}/{len(recent)}周期亏损，降低信心"

    return result


# ==================== 复盘写入 ====================

def save_review(period_label: str, stats: dict | None, ai_analysis: dict | None = None,
                decision: dict | None = None):
    """每次汇总后写入复盘JSON，包含决策依据"""
    review = {
        "time": datetime.now().isoformat(),
        "period": period_label,
        "total_trades": stats.get("total_trades", 0) if stats else 0,
        "total_pnl": round(stats.get("total_pnl", 0), 2) if stats else 0,
        "win_rate": stats.get("win_rate", 0) if stats else 0,
        "long_short": f"{stats.get('long_count',0)}多/{stats.get('short_count',0)}空" if stats else "",
        "data_source": decision.get("reason", "未知") if decision else "未知",
        "used_square": decision.get("use_square", False) if decision else False,
        "ai_root_cause": ai_analysis.get("root_cause", "") if ai_analysis else "",
        "ai_suggestion": ai_analysis.get("suggestions", "") if ai_analysis else "",
    }

    from utils.db import insert_review
    insert_review(review)
    return review


def get_recent_review(n: int = 5) -> list:
    from utils.db import get_recent_reviews
    return get_recent_reviews(n)


def should_switch_strategy() -> dict:
    """判断是否需要切换交易策略（基于DB复盘数据）"""
    from utils.db import get_recent_reviews
    reviews = get_recent_reviews(6)
    if not reviews:
        return {"switch": False, "reason": "无历史数据"}

    win_rate_avg = sum(r.get("win_rate", 0) for r in reviews if r.get("total_trades", 0) > 0)
    valid = sum(1 for r in reviews if r.get("total_trades", 0) > 0)
    if valid == 0:
        return {"switch": False, "reason": "无有效交易周期"}

    avg_wr = win_rate_avg / valid
    total_pnl = sum(r.get("total_pnl", 0) for r in reviews)

    if avg_wr < 40 and total_pnl < 0:
        return {
            "switch": True,
            "reason": f"近{valid}周期平均胜率{avg_wr:.0f}%<40%且亏损{total_pnl:+.2f}，建议切换策略",
            "suggest": "reduce_leverage" if avg_wr < 30 else "change_symbol",
        }
    return {"switch": False, "reason": f"近{valid}周期平均胜率{avg_wr:.0f}% 状态正常"}
