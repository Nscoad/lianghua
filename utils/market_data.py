"""
市场数据收集 — 获取指定币种的轻量行情

供 AI 分析时参考，帮助更准确判断市场状况。
"""
from core.trader import client


def format_light_market_data(symbol: str) -> str:
    """
    轻量版市场数据（供AI强制平仓判断使用），仅含核心指标。
    较完整版减少约 50% token。
    """
    try:
        resp = client.rest_api.ticker24hr_price_change_statistics(symbol=symbol)
        inst = resp.data().actual_instance
        pnl = float(inst.price_change_percent)
        sign = "+" if pnl >= 0 else ""
        price = float(inst.last_price)

        lines = [f"===== {symbol} ====="]
        lines.append(f"  最新价: {price:.6f}  24h: {sign}{pnl:.2f}%")
        lines.append(f"  成交量: {float(inst.volume):.0f}")

        # 资金费率
        try:
            fr_resp = client.rest_api.get_funding_rate_history(symbol=symbol, limit=1)
            fr_data = fr_resp.data()
            if fr_data:
                fr = float(fr_data[0].funding_rate)
                lines.append(f"  资金费率: {fr*100:.4f}%")
        except Exception:
            pass

        # 持仓量
        try:
            oi_resp = client.rest_api.open_interest(symbol=symbol)
            lines.append(f"  持仓量: {float(oi_resp.data().open_interest):.0f}")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception:
        return ""
