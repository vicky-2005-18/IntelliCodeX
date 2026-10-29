
@echo off
setlocal enabledelayedexpansion

:: Force UTF-8 encoding in Windows Console
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "INTELLICODEX_FORCE_TUI=1"

TITLE IntelliCodeX Launch Manager (CLI and Local Engine)

:: Navigate to script directory
cd /d "%~dp0"

:: Virtual environment detection & Python executable resolution
set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
    call "%~dp0.venv\Scripts\activate.bat" >nul 2>&1
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
    call "%~dp0venv\Scripts\activate.bat" >nul 2>&1
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
    call "%~dp0..\.venv\Scripts\activate.bat" >nul 2>&1
) else if exist "%~dp0..\venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\venv\Scripts\python.exe"
    call "%~dp0..\venv\Scripts\activate.bat" >nul 2>&1
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
if "%~1"=="--mcp" goto :START_MCP
if "%~1"=="7" goto :START_MCP
if "%~1"=="--mcp-config" goto :MCP_CONFIG
if "%~1"=="8" goto :MCP_CONFIG

:MENU
cls
echo =======================================================================
echo                 INTELLICODEX LAUNCHER - CLI AND LOCAL ENGINE
echo =======================================================================
echo.
echo   [1] Run Interactive CLI (Ollama Mode - qwen2.5-coder:7b)
echo   [2] Run Interactive CLI (Offline Mode - TF-IDF / CPU-only)
echo   [3] Start Local Backend API Server (FastAPI - Port 8000)
echo   [4] Run with Docker Compose (MongoDB + Ollama + Backend)
echo   [5] Install / Update Python Dependencies
echo   [6] Sync / Push Code to GitHub
echo   [7] Start Model Context Protocol (MCP) Server for IDEs (Cursor/VSCode/Antigravity)
echo   [8] Print MCP IDE Configuration JSON
echo   [9] Exit
echo.
echo =======================================================================
set "choice="
set /p "choice=Select an option (1-9): "

if "!choice!"=="1" goto :START_CLI
if "!choice!"=="2" goto :START_CLI_OFFLINE
if "!choice!"=="3" goto :START_BACKEND
if "!choice!"=="4" goto :START_DOCKER
if "!choice!"=="5" goto :INSTALL_DEPS
if "!choice!"=="6" goto :UPDATE_GITHUB
if "!choice!"=="7" goto :START_MCP
if "!choice!"=="8" goto :MCP_CONFIG
if "!choice!"=="9" goto :END
echo Invalid choice, please try again.
pause
goto :MENU

:START_CLI
echo.
echo Running IntelliCodeX Interactive CLI (Ollama backend - qwen2.5-coder:7b)...
"%PYTHON_EXE%" cli.py sample_repo --backend ollama --model qwen2.5-coder:7b --tui
set "CLI_EXIT=!ERRORLEVEL!"
if not "!CLI_EXIT!"=="0" (
    echo.
    echo [ERROR] IntelliCodeX CLI exited with status code !CLI_EXIT!.
)
exit /b !CLI_EXIT!

:START_CLI_OFFLINE
echo.
echo Running IntelliCodeX Interactive CLI (Offline TF-IDF mode)...
"%PYTHON_EXE%" cli.py sample_repo --backend tfidf --tui
set "CLI_EXIT=!ERRORLEVEL!"
if not "!CLI_EXIT!"=="0" (
    echo.
    echo [ERROR] IntelliCodeX CLI exited with status code !CLI_EXIT!.
)
exit /b !CLI_EXIT!

:START_BACKEND
echo.
echo Launching IntelliCodeX FastAPI Backend API (Port 8000)...
"%PYTHON_EXE%" -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
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
"%PYTHON_EXE%" -m pip install -r requirements.txt
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

:START_MCP
echo.
echo Starting IntelliCodeX Model Context Protocol (MCP) stdio server...
echo Point your IDE (Cursor, Claude Desktop, Antigravity) to this server process.
"%PYTHON_EXE%" -m core.mcp_server --repo sample_repo
goto :END

:MCP_CONFIG
echo.
echo IntelliCodeX Model Context Protocol (MCP) Configuration for IDEs:
"%PYTHON_EXE%" -m core.mcp_server --config
pause
goto :MENU

:END
exit /b 0
