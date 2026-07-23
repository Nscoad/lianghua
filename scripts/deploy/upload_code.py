"""
上传项目代码到阿里云服务器，通过 SFTP
"""
import os, sys, tarfile, io, paramiko, time

HOST = "8.129.101.134"
USER = "root"
PASSWORD = "Sym20041214"
REMOTE_DIR = "/root/bot"

# 需要排除的目录/文件
EXCLUDE = {
    "venv", ".venv", "__pycache__", ".git", ".idea", ".trae",
    "node_modules", ".vscode",
    "data/market_monitor.db", "data/trading.db", "data/trade_records.jsonl",
    "data/market_analysis.json", "data/fast_state.json",
    "ali_key.pem", "ssh_server.py", "upload_code.py",
    "*.pyc", "__pycache__",
}

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def should_exclude(path):
    rel = os.path.relpath(path, PROJECT_DIR)
    if rel == ".":
        return False
    parts = rel.replace("\\", "/").split("/")
    for p in parts:
        if p in EXCLUDE or p.endswith(".pyc"):
            return True
    return False

print("正在打包代码...")
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    for root, dirs, files in os.walk(PROJECT_DIR):
        if should_exclude(root):
            continue
        for f in files:
            fp = os.path.join(root, f)
            if should_exclude(fp):
                continue
            rel = os.path.relpath(fp, PROJECT_DIR)
            tar.add(fp, arcname=rel)

buf.seek(0)
size_mb = len(buf.getvalue()) / 1024 / 1024
print(f"打包完成: {size_mb:.1f} MB，正在上传...")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=15)

sftp = client.open_sftp()
remote_tar = f"/root/bot/code.tar.gz"
with sftp.open(remote_tar, "wb") as f:
    f.write(buf.getvalue())
sftp.close()

print("上传完成，正在解压...")
stdin, stdout, stderr = client.exec_command(
    f"cd {REMOTE_DIR} && tar xzf code.tar.gz && rm code.tar.gz && echo 'deploy ok'"
)
print(stdout.read().decode().strip())
err = stderr.read().decode().strip()
if err:
    print(f"[WARN] {err}")

# 检查 Python 和 uv
stdin, stdout, stderr = client.exec_command("which python3; python3 --version 2>&1; which pip3 2>&1")
print("--- Server Python ---")
print(stdout.read().decode())
err = stderr.read().decode().strip()
if err:
    print(f"[STDERR] {err}")

client.close()
print("\n代码部署完成！")
