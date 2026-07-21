"""前置条件检查 + 状态查询"""
from datetime import datetime
from collector.square import ensure_chrome_debug
from config import DEEPSEEK_API_KEY
from utils.db import get_all_closed_trades


def check_prerequisites() -> bool:
    ok = True
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-你的key":
        print("[警告] DEEPSEEK_API_KEY 未配置，AI 分析将跳过。")
        ok = False
    if not ensure_chrome_debug():
        print("[错误] Chrome 调试模式启动失败。")
        return False
    return ok


def print_status():
    from strategy.risk_manager import load_risk_state
    from scheduler import RISK_INTERVAL
    state = load_risk_state()

    print(f"\n{'='*50}")
    print("  系统状态")
    print(f"{'='*50}")
    print(f"  风险监控:      每 {RISK_INTERVAL} 秒")
    print("  汇总报表:      每 60 秒检查（到点发 1h/3h/6h/12h/24h 到微信）")
    if state.get("symbol"):
        print(f"  当前持仓:      {state['symbol']}")
        print(f"  当前保证金基准: {state.get('current_margin',0):.2f} USDT")
        print(f"  原始开仓保证金: {state['original_margin']:.2f} USDT")
        print(f"  止盈减仓:     {'已完成' if state.get('tp_done') else '等待中'}")
    else:
        print("  当前持仓:   无")

    try:
        all_trades = get_all_closed_trades()
        total = len(all_trades)
        if total > 0:
            total_pnl = sum(r.get("realized_pnl", 0) for r in all_trades)
            win = sum(1 for r in all_trades if r.get("realized_pnl", 0) > 0)
            loss = sum(1 for r in all_trades if r.get("realized_pnl", 0) < 0)
            wr = f"{win}/{loss} ({win/(win+loss)*100:.1f}%)" if (win+loss) > 0 else "N/A"
            print(f"  总交易:      {total}笔 | 净盈亏: {total_pnl:+.2f} USDT | 胜率: {wr}")
    except Exception:
        pass
