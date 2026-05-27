@echo off
chcp 65001 >nul
title Excel Chart Tool

cd /d "%~dp0"

echo.
echo   ========================================
echo     Excel 智能图表工具  v8
echo   ========================================
echo.

echo [1/3] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8801.*LISTENING" 2^>nul') do (
    echo       关闭旧进程 PID=%%a
    taskkill /PID %%a /F >nul 2>&1
    ping -n 2 127.0.0.1 >nul
)
echo       端口 8801 已就绪

echo [2/3] 启动 Python 服务...
start "Excel-Chart-Server" /MIN python -B -m uvicorn app:app --host 127.0.0.1 --port 8801

echo [3/3] 等待服务就绪...
set /a count=0
:wait_loop
ping -n 2 127.0.0.1 >nul
set /a count+=1
powershell -Command "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8801/' -TimeoutSec 2 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    if %count% lss 30 goto wait_loop
    echo       启动超时，请手动检查
    pause
    exit /b 1
)

echo.
echo   ✅ 服务已启动
echo   📊 http://127.0.0.1:8801
echo.
start http://127.0.0.1:8801

echo   关闭此窗口不影响服务运行
pause >nul
