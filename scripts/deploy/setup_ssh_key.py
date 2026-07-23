"""将本地SSH公钥添加到服务器"""
import paramiko
import os

pubkey_path = os.path.expanduser("~/.ssh/id_ed25519.pub")
with open(pubkey_path) as f:
    pubkey = f.read().strip()

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('8.129.101.134', username='root', password='Sym20041214', timeout=10)

# 确保 ~/.ssh 目录存在
client.exec_command('mkdir -p ~/.ssh && chmod 700 ~/.ssh')

# 追加公钥
stdin, stdout, stderr = client.exec_command('cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys')
stdin.write(pubkey + '\n')
stdin.flush()
stdin.channel.shutdown_write()

err = stderr.read().decode().strip()
if err:
    print(f"错误: {err}")
else:
    print("公钥写入成功!")

client.close()
print("SSH密钥配置完成!")
