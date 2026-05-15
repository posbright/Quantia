@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM 本地执行脚本 — 利用本地计算资源执行完整数据流水线
REM
REM 适用场景：
REM   - 服务器内存不足（1.6GB），分析任务频繁 OOM
REM   - 本地计算机资源充足，手动触发数据处理
REM   - 结果直接写入远程数据库，服务器前端即时可见
REM
REM 使用方式：
REM   1. 直接双击运行（当日数据）
REM   2. 命令行: run_local.bat 2026-03-09（指定日期）
REM   3. 命令行: run_local.bat 2026-03-01,2026-03-02（多日期）
REM   4. 命令行: run_local.bat 2026-03-01 2026-03-09（日期区间）
REM
REM 注意：
REM   - 所有任务幂等安全，重复执行不会产生重复数据
REM   - 服务器 cron 会自动检测本地是否已完成，避免重复执行
REM ============================================================

cd /d %~dp0
cd ..\..
set PROJECT_ROOT=%cd%

REM === 从 .env 加载数据库配置（连接远程服务器）===
if exist "%PROJECT_ROOT%\.env" (
    echo [信息] 加载 .env 配置...
    for /f "usebackq tokens=1,* delims==" %%A in ("%PROJECT_ROOT%\.env") do (
        set "_line=%%A"
        if not "!_line:~0,1!"=="#" if not "%%A"=="" (
            set "%%A=%%B"
        )
    )
) else (
    echo [警告] 未找到 .env 文件，将使用默认数据库配置（127.0.0.1）
)

REM === 激活虚拟环境 ===
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
) else (
    echo [警告] 未找到 .venv，将使用系统 Python
)

cd quantia\job

REM === 本地模式标志（启用高并发、少延迟、大内存配置）===
if not defined QUANTIA_LOCAL_MODE set QUANTIA_LOCAL_MODE=1

REM === 显示 QUANTIA_DB_* 配置 ===
if not defined QUANTIA_DB_HOST set QUANTIA_DB_HOST=127.0.0.1
if not defined QUANTIA_DB_PORT set QUANTIA_DB_PORT=3306
if not defined QUANTIA_DB_DATABASE set QUANTIA_DB_DATABASE=quantiadb

REM === 高并发配置（利用本地充足的 CPU 和内存）===
REM 以下参数仅在 .env 未定义时使用本地默认值。
REM 若需自定义，请在 .env 中设置，无需修改此脚本。

REM 流式分析并发线程数（服务器默认 2，本地推荐 8-16）
if not defined QUANTIA_ANALYSIS_WORKERS set QUANTIA_ANALYSIS_WORKERS=16

REM 流式分析每批股票数（服务器默认 50，本地推荐 200-3000）
if not defined QUANTIA_BATCH_SIZE set QUANTIA_BATCH_SIZE=3000

REM 回测外层并发（按策略表，服务器默认 1，本地推荐 2-4）
if not defined QUANTIA_BACKTEST_OUTER_WORKERS set QUANTIA_BACKTEST_OUTER_WORKERS=4

REM 回测内层并发线程数（按股票，服务器默认 2，本地推荐 4-8）
if not defined QUANTIA_BACKTEST_INNER_WORKERS set QUANTIA_BACKTEST_INNER_WORKERS=4

REM 指标计算并发线程数（服务器默认 4，本地推荐 8-16）
if not defined QUANTIA_INDICATOR_WORKERS set QUANTIA_INDICATOR_WORKERS=8

REM K线形态识别并发线程数（服务器默认 4，本地推荐 8-16）
if not defined QUANTIA_KLINE_PATTERN_WORKERS set QUANTIA_KLINE_PATTERN_WORKERS=8

REM 策略计算并发线程数（服务器默认 4，本地推荐 8-16）
if not defined QUANTIA_STRATEGY_WORKERS set QUANTIA_STRATEGY_WORKERS=8

REM 策略外层并发数（按策略，服务器默认 2，本地推荐 4-6）
if not defined QUANTIA_STRATEGY_OUTER_WORKERS set QUANTIA_STRATEGY_OUTER_WORKERS=4

REM K线缓存更新并发数（服务器默认 2，本地推荐 4-8）
if not defined QUANTIA_KLINE_CACHE_WORKERS set QUANTIA_KLINE_CACHE_WORKERS=6

REM 批量日期作业并发数（服务器默认 3，本地推荐 4-8）
if not defined QUANTIA_BATCH_DATE_WORKERS set QUANTIA_BATCH_DATE_WORKERS=6

REM 数据爬取并发线程数（服务器默认 5，本地推荐 10-20）
if not defined QUANTIA_CRAWL_WORKERS set QUANTIA_CRAWL_WORKERS=10

REM 数据库连接池基础大小（服务器默认 2，本地推荐 5-10）
if not defined QUANTIA_DB_POOL_SIZE set QUANTIA_DB_POOL_SIZE=8

REM 数据库连接池溢出数（服务器默认 3，本地推荐 5-10）
if not defined QUANTIA_DB_MAX_OVERFLOW set QUANTIA_DB_MAX_OVERFLOW=8

REM 子进程默认超时（秒，服务器默认 1800）
if not defined QUANTIA_JOB_TIMEOUT set QUANTIA_JOB_TIMEOUT=1800

REM K线缓存子进程超时（秒，服务器默认 36000）
if not defined QUANTIA_KLINE_JOB_TIMEOUT set QUANTIA_KLINE_JOB_TIMEOUT=36000

REM === 数据库超时配置（远程连接适当放宽）===
if not defined QUANTIA_DB_CONNECT_TIMEOUT set QUANTIA_DB_CONNECT_TIMEOUT=30
if not defined QUANTIA_DB_READ_TIMEOUT set QUANTIA_DB_READ_TIMEOUT=60
if not defined QUANTIA_DB_WRITE_TIMEOUT set QUANTIA_DB_WRITE_TIMEOUT=60

REM === 重试配置（远程连接可能间歇性超时）===
if not defined QUANTIA_DB_MAX_RETRIES set QUANTIA_DB_MAX_RETRIES=3
if not defined QUANTIA_DB_RETRY_DELAY set QUANTIA_DB_RETRY_DELAY=10
if not defined QUANTIA_DB_CONN_RETRIES set QUANTIA_DB_CONN_RETRIES=3

REM === Python 编码配置（确保 cmd 中正确输出中文）===
set PYTHONIOENCODING=utf-8

echo ============================================================
echo  Quantia 本地数据处理
echo ============================================================
echo.
echo  数据库: %QUANTIA_DB_HOST%:%QUANTIA_DB_PORT%/%QUANTIA_DB_DATABASE%
echo  超时: 连接%QUANTIA_DB_CONNECT_TIMEOUT%s 读%QUANTIA_DB_READ_TIMEOUT%s 写%QUANTIA_DB_WRITE_TIMEOUT%s
echo  重试: %QUANTIA_DB_MAX_RETRIES%次 间隔%QUANTIA_DB_RETRY_DELAY%s
echo.
echo  并发配置:
echo    分析线程: %QUANTIA_ANALYSIS_WORKERS%  批量大小: %QUANTIA_BATCH_SIZE%
echo    指标线程: %QUANTIA_INDICATOR_WORKERS%  K线形态: %QUANTIA_KLINE_PATTERN_WORKERS%
echo    策略线程: %QUANTIA_STRATEGY_WORKERS%  策略外层: %QUANTIA_STRATEGY_OUTER_WORKERS%
echo    回测外层: %QUANTIA_BACKTEST_OUTER_WORKERS%  回测内层: %QUANTIA_BACKTEST_INNER_WORKERS%
echo    K线缓存: %QUANTIA_KLINE_CACHE_WORKERS%  日期批量: %QUANTIA_BATCH_DATE_WORKERS%
echo    数据爬取: %QUANTIA_CRAWL_WORKERS%  DB连接池: %QUANTIA_DB_POOL_SIZE%+%QUANTIA_DB_MAX_OVERFLOW%
echo.
echo  执行参数: %*
echo ============================================================
echo.

REM === 启动前预检：测试数据库连接 ===
echo [%date% %time%] 测试数据库连接...
python -c "import sys,os;sys.path.insert(0,os.path.abspath('../..'));import quantia.lib.database as m;import pymysql,time;t=time.time();c=pymysql.connect(**m.MYSQL_CONN_DBAPI);print(f'  连接成功 ({time.time()-t:.1f}s) MySQL {c.server_version}');c.close()" 2>&1
if errorlevel 1 (
    echo.
    echo [错误] 数据库连接失败！请检查：
    echo   1. 服务器 %QUANTIA_DB_HOST% 是否可达
    echo   2. 阿里云安全组是否放行了当前IP的3306端口
    echo   3. .env 中的密码是否正确
    echo.
    pause
    exit /b 1
)
echo.

if "%~1"=="" (
    echo [%date% %time%] 执行当日完整流水线...
    python execute_daily_job.py
) else (
    echo [%date% %time%] 执行指定日期流水线: %*
    python execute_daily_job.py %*
)

echo.
echo ============================================================
echo  执行完成！结果已写入远程数据库，服务器前端可查看。
echo ============================================================
pause
