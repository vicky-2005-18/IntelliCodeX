@echo off
setlocal enabledelayedexpansion

TITLE IntelliCodeX Launch Manager (CLI & Local Engine)

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
if "%~1"=="--cli" goto :START_CLI
if "%~1"=="1" goto :START_CLI
if "%~1"=="--cli-offline" goto :START_CLI_OFFLINE
if "%~1"=="2" goto :START_CLI_OFFLINE
if "%~1"=="--backend" goto :START_BACKEND
if "%~1"=="3" goto :START_BACKEND
if "%~1"=="--docker" goto :START_DOCKER
if "%~1"=="4" goto :START_DOCKER
if "%~1"=="--install" goto :INSTALL_DEPS
if "%~1"=="5" goto :INSTALL_DEPS
if "%~1"=="--push" goto :UPDATE_GITHUB
if "%~1"=="--sync" goto :UPDATE_GITHUB
if "%~1"=="6" goto :UPDATE_GITHUB

:MENU
cls
echo =======================================================================
echo                 INTELLICODEX LAUNCHER - CLI AND LOCAL ENGINE
echo =======================================================================
echo.
echo   [1] Run Interactive CLI (Ollama Mode - qwen2.5-coder)
echo   [2] Run Interactive CLI (Offline Mode - TF-IDF / CPU-only)
echo   [3] Start Local Backend API Server (FastAPI - Port 8000)
echo   [4] Run with Docker Compose (MongoDB + Ollama + Backend)
echo   [5] Install / Update Python Dependencies
echo   [6] Sync / Push Code to GitHub
echo   [7] Exit
echo.
echo =======================================================================
set /p choice="Select an option (1-7): "

if "%choice%"=="1" goto :START_CLI
if "%choice%"=="2" goto :START_CLI_OFFLINE
if "%choice%"=="3" goto :START_BACKEND
if "%choice%"=="4" goto :START_DOCKER
if "%choice%"=="5" goto :INSTALL_DEPS
if "%choice%"=="6" goto :UPDATE_GITHUB
if "%choice%"=="7" goto :END
echo Invalid choice, please try again.
pause
goto :MENU

:START_CLI
echo.
echo Running IntelliCodeX Interactive CLI (Ollama backend)...
python cli.py sample_repo --backend ollama
echo.
echo =======================================================================
echo IntelliCodeX CLI has stopped.
echo =======================================================================
set "RESTART_CLI=Y"
set /p "RESTART_CLI=Restart CLI? [Y/N] (default Y): "
if /i "%RESTART_CLI%"=="N" goto :MENU
goto :START_CLI

:START_CLI_OFFLINE
echo.
echo Running IntelliCodeX Interactive CLI (Offline TF-IDF mode)...
python cli.py sample_repo --backend tfidf
echo.
echo =======================================================================
echo IntelliCodeX CLI has stopped.
echo =======================================================================
set "RESTART_CLI=Y"
set /p "RESTART_CLI=Restart CLI? [Y/N] (default Y): "
if /i "%RESTART_CLI%"=="N" goto :MENU
goto :START_CLI_OFFLINE

:START_BACKEND
echo.
echo Launching IntelliCodeX FastAPI Backend API (Port 8000)...
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
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
echo Installing Python dependencies from requirements.txt...
pip install -r requirements.txt
echo.
echo All Python dependencies installed successfully!
pause
goto :MENU

:UPDATE_GITHUB
echo.
if exist "%~dp0update_github.bat" (
    call "%~dp0update_github.bat"
) else (
    echo update_github.bat not found in script directory.
    pause
)
goto :MENU

:END
exit /b 0
