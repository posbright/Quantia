@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM  后台服务管理脚本
REM
REM  用法:
REM    server.bat start     启动后端 + 前端
REM    server.bat stop      停止后端 + 前端
REM    server.bat restart   重启全部服务
REM    server.bat status    查看运行状态
REM    server.bat web       仅启动后端 Web (port 9988)
REM    server.bat front     仅启动前端 Vite dev (port 3000)
REM ============================================================

cd /d %~dp0
cd ..\..
set PROJECT_ROOT=%cd%
set VENV=%PROJECT_ROOT%\.venv\Scripts
set WEB_PORT=9988
set FRONT_PORT=3000
set LOG_DIR=%PROJECT_ROOT%\quantia\log
set WEB_LOG=%LOG_DIR%\web_service.log
set FRONT_LOG=%LOG_DIR%\front_dev.log

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if exist "%VENV%\activate.bat" call "%VENV%\activate.bat"

set PYTHONPATH=%PROJECT_ROOT%
set PYTHONIOENCODING=utf-8

if "%1"=="" goto :usage
if /i "%1"=="start"   goto :start_all
if /i "%1"=="stop"    goto :stop_all
if /i "%1"=="restart" goto :restart
if /i "%1"=="status"  goto :status
if /i "%1"=="web"     goto :start_web
if /i "%1"=="front"   goto :start_front
goto :usage

:start_all
call :start_web
call :start_front
goto :eof

:stop_all
call :stop_web
call :stop_front
goto :eof

:restart
call :stop_all
timeout /t 3 /nobreak >nul
call :start_all
goto :eof

REM ── 启动后端 ──
:start_web
echo [Backend] Checking port %WEB_PORT% ...
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %WEB_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        echo [Backend] Port %WEB_PORT% in use PID=%%p - skipped
        goto :eof
    )
)
echo [Backend] Starting Web service ...
start /b "" python "%PROJECT_ROOT%\quantia\web\web_service.py" > "%WEB_LOG%" 2>&1
timeout /t 8 /nobreak >nul
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %WEB_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        echo [Backend] Started OK  PID=%%p  http://localhost:%WEB_PORT%/
        goto :eof
    )
)
echo [Backend] Start FAILED - check log: %WEB_LOG%
goto :eof

REM ── 启动前端 ──
:start_front
echo [Frontend] Checking port %FRONT_PORT% ...
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %FRONT_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        echo [Frontend] Port %FRONT_PORT% in use PID=%%p - skipped
        goto :eof
    )
)
echo [Frontend] Starting Vite dev server ...
cd /d "%PROJECT_ROOT%\quantia\fontWeb"
start /b "" cmd /c "npm run dev > "%FRONT_LOG%" 2>&1"
cd /d "%PROJECT_ROOT%"
timeout /t 6 /nobreak >nul
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %FRONT_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        echo [Frontend] Started OK  PID=%%p  http://localhost:%FRONT_PORT%/
        goto :eof
    )
)
echo [Frontend] Start FAILED - check log: %FRONT_LOG%
goto :eof

REM ── 停止后端 ──
:stop_web
echo [Backend] Stopping ...
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %WEB_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        taskkill /F /PID %%p >nul 2>&1
        echo [Backend] Stopped PID=%%p
        goto :eof
    )
)
echo [Backend] Not running
goto :eof

REM ── 停止前端 ──
:stop_front
echo [Frontend] Stopping ...
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %FRONT_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        taskkill /F /PID %%p >nul 2>&1
        echo [Frontend] Stopped PID=%%p
        goto :eof
    )
)
echo [Frontend] Not running
goto :eof

REM ── 状态查询 ──
:status
echo ====== Service Status ======
set WEB_UP=0
set FRONT_UP=0
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %WEB_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        echo [Backend]  RUNNING  PID=%%p  http://localhost:%WEB_PORT%/
        set WEB_UP=1
    )
)
if !WEB_UP!==0 echo [Backend]  STOPPED

for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %FRONT_PORT% -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess"') do (
    if "%%p" NEQ "" (
        echo [Frontend] RUNNING  PID=%%p  http://localhost:%FRONT_PORT%/
        set FRONT_UP=1
    )
)
if !FRONT_UP!==0 echo [Frontend] STOPPED
echo =============================
goto :eof

:usage
echo.
echo   Server Management Script
echo   ────────────────────────────
echo   Usage: %~nx0 ^<command^>
echo.
echo   Commands:
echo     start     Start backend + frontend
echo     stop      Stop backend + frontend
echo     restart   Restart all services
echo     status    Check running status
echo     web       Start backend only  (port %WEB_PORT%)
echo     front     Start frontend only (port %FRONT_PORT%)
echo.
goto :eof
