"""在阿里云服务器上配置 Nginx 反向代理到本地看板"""
import paramiko
import time

NGINX_CONF = """
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache_bypass $http_upgrade;
        client_max_body_size 10m;
    }
}
"""

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('8.129.101.134', username='root', password='Sym20041214', timeout=10)

# 写 Nginx 配置
stdin, stdout, stderr = client.exec_command('cat > /etc/nginx/conf.d/dashboard.conf')
stdin.write(NGINX_CONF)
stdin.flush()
stdin.channel.shutdown_write()
out = stdout.read().decode()
err = stderr.read().decode()
print("写配置:", out[:100] if out else "(空)")
if err:
    print("错误:", err[:200])

# 删除默认配置
client.exec_command('rm -f /etc/nginx/conf.d/default.conf')

# 测试配置并启动
stdin, stdout, stderr = client.exec_command('nginx -t 2>&1')
time.sleep(1)
print("配置测试:", stdout.read().decode()[:300])

stdin, stdout, stderr = client.exec_command('nginx -s stop 2>/dev/null; sleep 1; nginx 2>&1')
time.sleep(2)
print("启动:", stdout.read().decode()[:200])
err = stderr.read().decode()[:200]
if err:
    print("启动错误:", err)

# 检查状态
stdin, stdout, stderr = client.exec_command('systemctl status nginx 2>&1 | head -8')
time.sleep(1)
print("状态:", stdout.read().decode())

# 放行防火墙端口
client.exec_command('firewall-cmd --add-port=80/tcp --permanent 2>/dev/null; firewall-cmd --reload 2>/dev/null')
print("防火墙已放行 80 端口")

client.close()
print("\nNginx 配置完成! 公网: http://8.129.101.134")
