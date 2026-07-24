"""
系统启动器 — 简单菜单启动/停止交易机器人、看板、SSH隧道
增加：
1. 防止 scheduler.py 重复启动
2. 防止 dashboard 重复启动
3. 保存PID，只停止自己启动的进程
"""

import os
import sys
import subprocess
import time
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

PID_FILE = os.path.join(BASE, "data", "launcher_pids.json")

# 代码最后修改时间（用于确认是否最新代码）
LAST_UPDATED = "2026-07-24 18:30+08:00"

# 确保 data/ 目录存在
os.makedirs(os.path.join(BASE, "data"), exist_ok=True)


def run(cmd):
    """后台启动进程"""
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    p = subprocess.Popen(
        cmd,
        shell=True,
        startupinfo=info,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return p.pid


def load_pids():
    if not os.path.exists(PID_FILE):
        return {}

    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_pids(data):
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_pid_running(pid):
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True
        )
        return str(pid) in r.stdout
    except:
        return False


def already_running(name):
    pids = load_pids()

    if name in pids and is_pid_running(pids[name]):
        return True

    return False


def start_bot():
    if already_running("bot"):
        print("  [Bot] 已经运行，跳过")
        return

    print("  [Bot] 启动交易机器人...")
    pid = run("uv run python scheduler.py forever")

    pids = load_pids()
    pids["bot"] = pid
    save_pids(pids)

    print(f"  [Bot] 已启动 PID={pid}")


def start_dashboard():
    if already_running("dashboard"):
        print("  [Web] 看板已经运行")
    else:
        print("  [Web] 启动看板...")
        pid = run("uv run python run_dashboard.py")
        pids = load_pids()
        pids["dashboard"] = pid
        save_pids(pids)

    time.sleep(3)

    if already_running("ssh"):
        print("  [SSH] 隧道已经运行")
    else:
        print("  [SSH] 启动隧道...")
        pid = run(
            'ssh -N -R 5000:127.0.0.1:5000 '
            '-o ServerAliveInterval=30 '
            '-o ServerAliveCountMax=3 '
            '-o ExitOnForwardFailure=yes '
            '-o UserKnownHostsFile=NUL '
            '-o StrictHostKeyChecking=no '
            'root@8.129.101.134'
        )

        pids = load_pids()
        pids["ssh"] = pid
        save_pids(pids)

    print("  [OK] 看板+隧道运行中")
    print("  [URL] http://8.129.101.134")


def start_all():
    start_bot()
    start_dashboard()


def stop_all():
    print("  [STOP] 正在停止...")

    pids = load_pids()

    for name, pid in pids.items():
        if is_pid_running(pid):
            os.system(f"taskkill /f /pid {pid} >nul 2>&1")
            print(f"  已停止 {name} PID={pid}")

    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

    print("  [OK] 已停止启动器管理的进程")


def show_status():
    pids = load_pids()

    print("  当前状态:")
    print("-" * 25)

    if not pids:
        print("  没有记录")
        return

    for name, pid in pids.items():
        status = "运行中" if is_pid_running(pid) else "已停止"
        print(f"  {name:<12} PID={pid:<8} {status}")


ACTIONS = {
    "1": ("启动交易机器人", start_bot),
    "2": ("启动看板+隧道", start_dashboard),
    "3": ("全部启动", start_all),
    "4": ("全部停止", stop_all),
    "5": ("查看状态", show_status),
}


def main():
    while True:
        os.system("cls")

        print("=" * 30)
        print("   启动量化交易系统")
        print(f"   更新: {LAST_UPDATED}")
        print("=" * 30)

        for k, (label, _) in sorted(ACTIONS.items()):
            print(f"  {k}. {label}")

        print("  0. 退出\n")

        try:
            c = input("  请选择: ").strip()
        except KeyboardInterrupt:
            break

        if c == "0":
            break

        if c in ACTIONS:
            try:
                ACTIONS[c][1]()
            except Exception as e:
                print("[ERROR]", e)
        else:
            print("无效选择")

        input("\n按 Enter 返回菜单...")


if __name__ == "__main__":
    main()
