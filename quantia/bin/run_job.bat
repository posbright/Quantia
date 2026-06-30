chcp 65001
@echo off
rem Python 解释器：显式 PYTHON_BIN > 项目本地 .venv > 系统 python
set "PY=python"
if not "%PYTHON_BIN%"=="" (
    set "PY=%PYTHON_BIN%"
) else if exist "%~dp0..\..\.venv\Scripts\python.exe" (
    set "PY=%~dp0..\..\.venv\Scripts\python.exe"
)
cd %~dp0
cd ..
cd job
echo ------整体作业（可选指定单个交易日）------
echo 最近交易日作业 run_job.bat
echo 指定单个交易日 run_job.bat 2026-02-24
echo （暂不支持多日期/区间：子作业按实时数据运行，无法回补历史区间）
echo ------数据获取与分析（拆分模式）------
echo 数据获取（API调用+K线缓存） python fetch_daily_job.py
echo 数据分析（指标+策略+回测） python analysis_daily_job.py
echo ------单功能作业，除了创建数据库，其他都支持批量作业------
echo 创建数据库作业 python init_job.py
echo 数据获取（K线缓存更新） python fetch_data_job.py
echo 综合选股作业 python selection_data_daily_job.py
echo 基础数据实时作业 python basic_data_daily_job.py
echo 基础数据非实时作业 python basic_data_other_daily_job.py
echo 流式分析（指标+K线+策略） python streaming_analysis_job.py
echo 指标数据作业（旧版独立） python indicators_data_daily_job.py
echo K线形态作业（旧版独立） python klinepattern_data_daily_job.py
echo 策略数据作业（旧版独立） python strategy_data_daily_job.py
echo 回测数据 python backtest_data_daily_job.py
echo 收盘后数据 python basic_data_after_close_daily_job.py
echo ------正在执行作业中，请等待------
"%PY%" execute_daily_job.py %*
pause
exit
