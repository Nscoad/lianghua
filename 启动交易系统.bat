@echo off
chcp 936 >nul
cd /d "%~dp0"

:MENU
cls
echo ============================
echo   启动量化交易系统
echo ============================
echo.
echo   1. 启动交易机器人
echo   2. 启动看板和隧道
echo   3. 全部启动
echo   4. 全部停止
echo.
set /p choice="请选择 (1/2/3/4): "

if "%choice%"=="1" goto START_BOT
if "%choice%"=="2" goto START_DASH
if "%choice%"=="3" goto START_ALL
if "%choice%"=="4" goto STOP_ALL
echo 无效选择
timeout /t 2 >nul
goto MENU

:START_BOT
echo [Bot] 启动交易机器人...
start /min "" "%ComSpec%" /c "uv run python scheduler.py forever"
echo [Bot] 已启动
goto DONE

:START_DASH
echo [Web] 启动看板...
start /min "" "%ComSpec%" /c "uv run python run_dashboard.py"
timeout /t 3 >nul
echo [SSH] 启动隧道...
start /min "" "%ComSpec%" /c "ssh -N -R 5000:127.0.0.1:5000 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o UserKnownHostsFile=NUL -o StrictHostKeyChecking=no root@8.129.101.134"
echo.
echo [OK] 看板 + 隧道已启动
echo [URL] http://8.129.101.134
echo [LOCAL] http://localhost:5000
goto DONE

:START_ALL
echo [Bot] 启动交易机器人...
start /min "" "%ComSpec%" /c "uv run python scheduler.py forever"
echo [Web] 启动看板...
start /min "" "%ComSpec%" /c "uv run python run_dashboard.py"
timeout /t 3 >nul
echo [SSH] 启动隧道...
start /min "" "%ComSpec%" /c "ssh -N -R 5000:127.0.0.1:5000 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o UserKnownHostsFile=NUL -o StrictHostKeyChecking=no root@8.129.101.134"
echo.
echo [OK] 全部启动完成!
echo [URL] http://8.129.101.134
goto DONE

:STOP_ALL
echo [STOP] 正在停止...
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im ssh.exe >nul 2>&1
echo [OK] 已停止
goto DONE

:DONE
echo.
pause
