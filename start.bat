@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

title 元末纪事 - 一键启动
echo ============================================
echo   元末纪事（元末明初历史模拟）一键启动
echo ============================================
echo.

rem ---- 环境检查 ----
where python >nul 2>nul || (echo [错误] 未找到 Python，请先安装 Python 3.10+ 并加入 PATH & goto :fail)
where npm >nul 2>nul || (echo [错误] 未找到 Node.js/npm，请先安装 Node.js 18+ 并加入 PATH & goto :fail)

if not exist "backend\main.py" (echo [错误] 找不到 backend 目录，请确认在项目根目录运行 & goto :fail)

rem ---- 后端依赖检查 ----
pushd backend
python -c "import fastapi, uvicorn, aiosqlite" >nul 2>nul
if errorlevel 1 (
    echo [提示] 后端依赖未安装，正在安装...
    python -m pip install -r requirements.txt
    if errorlevel 1 (echo [错误] 后端依赖安装失败 & popd & goto :fail)
)
popd

rem ---- 前端依赖检查 ----
if not exist "frontend\node_modules" (
    echo [提示] 首次运行，安装前端依赖（可能需要几分钟）...
    pushd frontend
    call npm install
    if errorlevel 1 (echo [错误] 前端依赖安装失败 & popd & goto :fail)
    popd
)

rem ---- AI 供应商检查提示 ----
echo.
echo [提示] 本游戏没有内置 Mock 供应商，必须配置真实的 AI 供应商才能游玩。
echo       启动后请在页面右上角「AI 设置」中填写 API Key 等信息。
echo.

rem ---- 启动前后端 ----
echo [1/2] 启动后端服务  http://localhost:8000
start "元末纪事-后端" cmd /k "cd /d %~dp0backend && python -m uvicorn main:app --port 8000"

echo [2/2] 启动前端服务  http://localhost:5173
start "元末纪事-前端" cmd /k "cd /d %~dp0frontend && npm run dev"

echo 等待服务就绪...
timeout /t 6 /nobreak >nul
start "" http://localhost:5173
echo.
echo 已启动！浏览器将自动打开 http://localhost:5173
echo 如未自动打开，请手动访问该地址。
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
