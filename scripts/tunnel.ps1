# SSH 反向隧道 — 把本地看板映射到阿里云服务器
# 用法: .\tunnel.ps1
# 服务器公网: http://8.129.101.134

$HOST = "8.129.101.134"
$USER = "root"
$LOCAL_PORT = 5000
$REMOTE_PORT = 5000

Write-Host "建立 SSH 反向隧道..." -ForegroundColor Cyan
Write-Host "服务器 $REMOTE_PORT : 本地 $LOCAL_PORT" -ForegroundColor Gray
Write-Host "公网访问: http://$HOST" -ForegroundColor Green
Write-Host "按 Ctrl+C 关闭隧道`n" -ForegroundColor Yellow

ssh -N -R "${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}" `
    -o ServerAliveInterval=30 `
    -o ServerAliveCountMax=3 `
    -o ExitOnForwardFailure=yes `
    -o UserKnownHostsFile=NUL `
    -o StrictHostKeyChecking=no `
    "${USER}@${HOST}"
