"""
PushPlus 微信推送通知 — 定时汇总报表（1h/3h/6h/12h/24h）
"""
import json
import os
import requests
from config import PUSHPLUS_TOKEN

BALANCE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "balance_snapshots.json")


def _get_balance_info() -> dict:
    """获取期初余额和当前余额"""
    from core.trader import check_balance
    current = check_balance() or 0

    prev = None
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                prev = data.get("balance", current)
        except Exception:
            prev = current

    # 保存当前余额作为下次的期初
    os.makedirs(os.path.dirname(BALANCE_FILE), exist_ok=True)
    with open(BALANCE_FILE, "w", encoding="utf-8") as f:
        json.dump({"balance": current, "time": __import__('datetime').datetime.now().isoformat()}, f)

    return {"prev": prev or current, "current": current}


def send_notification(title: str, content: str) -> bool:
    """通过 PushPlus 发送微信通知；token 为空或发送失败时静默返回 False"""
    if not PUSHPLUS_TOKEN:
        return False
    try:
        resp = requests.post(
            "http://www.pushplus.plus/send",
            data={"token": PUSHPLUS_TOKEN, "title": title, "content": content},
            timeout=10,
        )
        ok = resp.status_code == 200 and resp.json().get("code") == 200
        if not ok:
            print(f"[通知] 发送失败: {resp.text[:200]}")
        return ok
    except Exception as e:
        print(f"[通知] 发送异常: {e}")
        return False


def send_summary_report(period_label: str, stats: dict, ai_analysis: dict | None = None):
    """发送汇总报表到微信（含余额变化 + AI复盘分析）"""
    if not stats:
        send_notification(f"📊 {period_label} 汇总", f"{period_label}内无平仓记录")
        return

    total_pnl = stats["total_pnl"]
    win = stats["win"]
    loss = stats["loss"]
    total = win + loss
    win_rate = stats["win_rate"]

    long_count = stats.get("long_count", 0)
    short_count = stats.get("short_count", 0)
    long_pnl = stats.get("long_pnl", 0)
    short_pnl = stats.get("short_pnl", 0)

    # 余额变化
    balance_info = _get_balance_info()
    prev_bal = balance_info["prev"]
    curr_bal = balance_info["current"]
    bal_change = curr_bal - prev_bal

    lines = [f"<h3>📊 {period_label} 交易汇总</h3>"]
    lines.append(f"<b>时间:</b> {stats.get('time', '')[:19]}<br>")

    lines.append("<hr>")
    lines.append("<b>💰 余额变化</b><br>")
    lines.append(f"期初余额: {prev_bal:.2f} USDT<br>")
    lines.append(f"当前余额: <b>{curr_bal:.2f} USDT</b><br>")
    lines.append(f"变化: <b>{bal_change:+.2f} USDT</b><br>")

    lines.append("<hr>")
    lines.append("<b>📋 总览</b><br>")
    lines.append(f"总平仓: {total} 笔<br>")
    lines.append(f"净盈亏: <b>{total_pnl:+.2f} USDT</b><br>")
    lines.append(f"胜率: {win}胜/{loss}败 ({win_rate}%)<br>")

    lines.append("<hr>")
    lines.append("<b>🔄 多空统计</b><br>")
    lines.append(f"做多: {long_count} 笔 ({long_pnl:+.2f} USDT)<br>")
    lines.append(f"做空: {short_count} 笔 ({short_pnl:+.2f} USDT)<br>")

    # 原因分类
    if stats.get("by_reason"):
        lines.append("<hr>")
        lines.append("<b>📌 原因分布</b><br>")
        for r in stats["by_reason"]:
            label = r["label"]
            cnt = r["count"]
            pnl = r["pnl"]
            wr = r["win_rate"]
            lines.append(f"{label}: {cnt}次 ({pnl:+.2f} USDT, 胜率{wr}%)<br>")

    # 币种明细
    if stats.get("by_symbol"):
        lines.append("<hr>")
        lines.append("<b>🪙 币种明细</b><br>")
        for s in stats.get("by_symbol", []):
            lines.append(f"{s['symbol']}: {s['pnl']:+.2f} USDT ({s['win']}胜/{s['loss']}败/{s['total']}次)<br>")

    # AI分析
    if ai_analysis:
        lines.append("<hr>")
        lines.append("<b>🤖 AI 复盘分析</b><br>")
        rc = ai_analysis.get("root_cause", "")
        details = ai_analysis.get("details", "")
        suggestions = ai_analysis.get("suggestions", "")
        adjustment = ai_analysis.get("adjustment", "")
        if rc:
            lines.append(f"<b>根因:</b> {rc}<br>")
        if details:
            lines.append(f"<b>分析:</b> {details}<br>")
        if suggestions:
            lines.append(f"<b>建议:</b> {suggestions}<br>")
        if adjustment and adjustment != "暂无":
            lines.append(f"<b>参数调整:</b> {adjustment}<br>")

    # 使用换行符作为分隔（PushPlus 的 text 模式）
    content = "\n".join(lines)

    emoji = "📈" if total_pnl > 0 else "📉"
    send_notification(f"{emoji} {period_label} 汇总 ({total_pnl:+.1f}U)", content)
