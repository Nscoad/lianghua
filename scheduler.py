"""
调度器入口 — 转发到 scheduler/ 包
"""
import sys
from scheduler import run_forever

if __name__ == "__main__":
    run_forever() if "forever" in sys.argv else run_forever()
