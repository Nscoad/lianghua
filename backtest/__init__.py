"""
Streaming 流式回测框架 — 逐 K 线回放，杜绝未来函数

用法：
  uv run python -m backtest --symbol BANKUSDT --interval 1h --days 30
"""
import argparse
from backtest.engine import run_streaming_backtest
from backtest.report import print_report


def main():
    parser = argparse.ArgumentParser(description="Streaming Backtest")
    parser.add_argument("--symbol", default="BANKUSDT", help="币种")
    parser.add_argument("--interval", default="1h", help="K线周期: 15m/1h/4h/1d")
    parser.add_argument("--days", type=int, default=30, help="回测天数")
    parser.add_argument("--margin", type=float, default=100, help="初始保证金 USDT")
    parser.add_argument("--leverage", type=int, default=5, help="杠杆")
    args = parser.parse_args()

    trades = run_streaming_backtest(args.symbol, args.interval, args.days, args.margin, args.leverage)
    print_report(trades, args.symbol, args.interval, args.days)


if __name__ == "__main__":
    main()
