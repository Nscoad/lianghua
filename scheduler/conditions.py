"""前置条件检查 + 状态查询"""
from config import DEEPSEEK_API_KEY
from utils.db import get_all_closed_trades



def check_prerequisites() -> bool:
    ok = True
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-你的key":
        print("[警告] DEEPSEEK_API_KEY 未配置，AI 分析将跳过。")
        # 不阻止启动，只警告
    return ok


def print_status():
    from utils.trade.fast_trader import _load_state

    fast_state = _load_state()
    positions = fast_state.get("positions", {})
    active = sum(1 for p in positions.values() if not p.get("closed", False))

    print(f"\n{'='*50}")
    print("  系统状态")
    print(f"{'='*50}")
    print("  快捞监测:     每 2 分钟")
    print(f"  快捞仓位:     {active} 个")
    if active > 0:
        for sym, p in positions.items():
            if not p.get("closed", False):
                print(f"    {sym} {p.get('side','?')} 开@{p.get('entry_price',0)}")

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
