@echo off
echo Starting Chongzhen Simulator...

start "Backend" cmd /k "cd /d %~dp0backend && pip install -r requirements.txt >nul 2>&1 && python -m uvicorn main:app --reload --port 8000"
timeout /t 3 /nobreak >nul
start "Frontend" cmd /k "cd /d %~dp0frontend && npm install >nul 2>&1 && npm run dev"

echo Both services starting. Backend: http://localhost:8000 Frontend: http://localhost:5173
