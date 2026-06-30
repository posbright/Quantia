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
cd web
"%PY%" web_service.py
echo ------Web服务已启动，请不要关闭------
echo 访问地址 : http://localhost:9988/
pause
exit
