@echo off
setlocal enabledelayedexpansion

:: Force UTF-8 encoding in Windows Console
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "INTELLICODEX_FORCE_TUI=1"

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

:CLI_LOOP
echo Launching IntelliCodeX Interactive CLI...
if "%~1"=="" (
    "%PYTHON_EXE%" cli.py sample_repo --backend ollama --tui
) else (
    "%PYTHON_EXE%" cli.py %*
)

echo.
echo =======================================================================
echo IntelliCodeX CLI has stopped.
echo =======================================================================
set "RESTART_CLI=Y"
set /p "RESTART_CLI=Restart CLI? [Y/N] (default Y): "
if /i "!RESTART_CLI!"=="N" goto :CLI_EXIT
echo.
goto :CLI_LOOP

:CLI_EXIT
exit /b 0
