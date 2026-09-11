@echo off
chcp 65001
cd /d "%~dp0"
set DB_ENGINE=sqlite
echo ======================================
echo   大狗嚼电竞管理系统 - 本地启动中...
echo ======================================
echo.
echo 数据库: SQLite (本地文件)
echo 访问地址: http://localhost:8000
echo API文档: http://localhost:8000/docs
echo.
echo 按 Ctrl+C 停止服务
echo ======================================
echo.
D:\python\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
