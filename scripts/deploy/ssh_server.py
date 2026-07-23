"""
SSH 到阿里云服务器执行命令
"""
import subprocess
import sys

HOST = "8.129.101.134"
USER = "root"
PASSWORD = "Sym20041214"

if len(sys.argv) > 1:
    cmd = " ".join(sys.argv[1:])
else:
    cmd = "echo 'SSH OK'; uname -a; cat /etc/os-release | head -3"

# 用 sshpass （如果装了）或 python 的 paramiko
try:
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
    stdin, stdout, stderr = client.exec_command(cmd)
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print(f"[STDERR] {err}", file=sys.stderr)
    client.close()
except ImportError:
    # fallback: sshpass
    full_cmd = f'sshpass -p "{PASSWORD}" ssh -o StrictHostKeyChecking=no {USER}@{HOST} "{cmd}"'
    subprocess.run(full_cmd, shell=True)
except Exception as e:
    print(f"[ERROR] {e}")
