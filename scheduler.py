"""
调度器入口 — 转发到 scheduler/ 包
"""
import sys
from scheduler import run_forever, run_once

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    run_forever() if mode == "forever" else run_once()
