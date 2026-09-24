@echo off
cd /d "%~dp0"

rem ============================================================
rem  大狗嚼电竞管理系统 - 启动后端
rem  本脚本固定使用本项目的虚拟环境，避免误用系统 Python
rem  或其它项目的虚拟环境（那是 ModuleNotFoundError 的头号原因）
rem ============================================================

set "PY=%~dp0venv\Scripts\python.exe"

echo ============================================================
echo   大狗嚼电竞管理系统 - 启动后端
echo ============================================================
echo   解释器  : %PY%
echo   数据库  : MySQL (库 game_escort_club)
echo   访问地址: http://localhost:8000
echo   接口文档: http://localhost:8000/docs
echo   停止服务: 按 Ctrl+C
echo ============================================================
echo.

if not exist "%PY%" goto NO_PY

rem 先确认关键依赖真的装在这个环境里，早失败、早提示
"%PY%" -c "import fastapi, uvicorn, sqlalchemy, pymysql, jose, bcrypt" 2>nul
if errorlevel 1 goto NO_DEP

"%PY%" "%~dp0main.py"
echo.
echo 服务已停止。
pause
exit /b 0

:NO_PY
echo [错误] 找不到虚拟环境解释器：
echo        %PY%
echo.
echo 请先按 README 的「第 1 步：创建虚拟环境」「第 2 步：安装依赖」完成后重试。
echo.
pause
exit /b 1

:NO_DEP
echo [错误] 该虚拟环境缺少必要依赖。
echo        请在 backend 目录执行： venv\Scripts\pip install -r requirements.txt
echo.
pause
exit /b 1
