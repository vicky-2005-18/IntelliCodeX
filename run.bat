@echo off
setlocal enabledelayedexpansion

TITLE IntelliCodeX Launch Manager

:: Navigate to script directory
cd /d "%~dp0"

:: Virtual environment detection
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist "..\venv\Scripts\activate.bat" (
    call ..\venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "..\.venv\Scripts\activate.bat" (
    call ..\.venv\Scripts\activate.bat
)

:: Check CLI arguments
if "%~1"=="--full" goto :START_FULL
if "%~1"=="1" goto :START_FULL
if "%~1"=="--backend" goto :START_BACKEND
if "%~1"=="2" goto :START_BACKEND
if "%~1"=="--frontend" goto :START_FRONTEND
if "%~1"=="3" goto :START_FRONTEND
if "%~1"=="--cli" goto :START_CLI
if "%~1"=="4" goto :START_CLI
if "%~1"=="--docker" goto :START_DOCKER
if "%~1"=="5" goto :START_DOCKER
if "%~1"=="--install" goto :INSTALL_DEPS
if "%~1"=="6" goto :INSTALL_DEPS

:MENU
cls
echo =======================================================================
echo                         INTELLICODEX LAUNCHER
echo =======================================================================
echo.
echo   [1] Start Full Application (Backend + Frontend)
echo   [2] Start Backend API Server Only (FastAPI - Port 8000)
echo   [3] Start Frontend Web App Only (Vite React - Port 5173)
echo   [4] Run Interactive CLI Tool (Offline TF-IDF / Ollama)
echo   [5] Run with Docker Compose (MongoDB + Ollama + Backend)
echo   [6] Install / Update Dependencies (Python + Node.js)
echo   [7] Exit
echo.
echo =======================================================================
set /p choice="Select an option (1-7): "

if "%choice%"=="1" goto :START_FULL
if "%choice%"=="2" goto :START_BACKEND
if "%choice%"=="3" goto :START_FRONTEND
if "%choice%"=="4" goto :START_CLI
if "%choice%"=="5" goto :START_DOCKER
if "%choice%"=="6" goto :INSTALL_DEPS
if "%choice%"=="7" goto :END
echo Invalid choice, please try again.
pause
goto :MENU

:START_FULL
echo.
echo [1/2] Launching IntelliCodeX Enterprise FastAPI Backend...
start "IntelliCodeX Backend API" cmd /k "cd /d "%~dp0" && python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"

echo [2/2] Launching IntelliCodeX Frontend React App...
if not exist "frontend\node_modules" (
    echo node_modules not found. Installing frontend dependencies...
    cd frontend && call npm install && cd ..
)
start "IntelliCodeX Frontend UI" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo =======================================================================
echo IntelliCodeX is launching!
echo   - Backend API:  http://localhost:8000 (Docs: http://localhost:8000/docs)
echo   - Frontend UI: http://localhost:5173
echo =======================================================================
echo.
pause
goto :END

:START_BACKEND
echo.
echo Launching IntelliCodeX FastAPI Backend...
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
pause
goto :END

:START_FRONTEND
echo.
if not exist "frontend\node_modules" (
    echo node_modules not found. Installing dependencies...
    cd frontend && call npm install && cd ..
)
echo Launching IntelliCodeX Frontend UI...
cd frontend
npm run dev
pause
goto :END

:START_CLI
echo.
echo Running IntelliCodeX Interactive CLI...
python cli.py sample_repo --backend tfidf
pause
goto :END

:START_DOCKER
echo.
echo Starting IntelliCodeX via Docker Compose...
docker-compose up --build
pause
goto :END

:INSTALL_DEPS
echo.
echo Installing Python dependencies...
pip install -r requirements.txt

echo.
echo Installing Frontend Node.js dependencies...
cd frontend
call npm install
cd ..
echo.
echo All dependencies installed successfully!
pause
goto :MENU

:END
exit /b 0
