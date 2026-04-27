@echo off
setlocal

:: Kill leftover services from previous run
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /pid %%a /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /pid %%a /f >nul 2>&1

:: Start Backend and Frontend silently in background
start /b cmd /c "cd /d %~dp0backend && python -m uvicorn main:app --reload --port 8000 >nul 2>&1"
start /b cmd /c "cd /d %~dp0frontend && npm run dev -- --no-open >nul 2>&1"

:: Wait for services, then open game page
timeout /t 5 /nobreak >nul
start http://localhost:5173/

echo Game opened. Press any key to stop all services...
pause >nul

:: Cleanup
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /pid %%a /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /pid %%a /f >nul 2>&1

endlocal
