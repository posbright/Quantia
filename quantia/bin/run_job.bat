chcp 65001
@echo off
cd %~dp0
cd ..
cd job
echo ------整体作业，支持批量作业------
echo 当前时间作业 python execute_daily_job.py
echo 1个时间作业 python execute_daily_job.py 2026-02-24
echo N个时间作业 python execute_daily_job.py 2026-02-24,2026-02-25
echo 区间作业 python execute_daily_job.py 2026-02-01 2026-02-25
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
python execute_daily_job.py
pause
exit
