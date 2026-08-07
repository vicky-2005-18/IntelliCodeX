@echo off
cd /d "%~dp0frontend"
if not exist "node_modules" (
    echo node_modules not found. Installing frontend dependencies...
    call npm install
)
echo Starting IntelliCodeX Frontend React App on http://localhost:5173 ...
npm run dev
pause
