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
) else (
    :: Fallback: verify default python has dependencies; if not, check py launcher for Python 3.12/3.14
    "%PYTHON_EXE%" -c "import rich, requests" >nul 2>&1
    if not "!ERRORLEVEL!"=="0" (
        for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%I"
        if "!PYTHON_EXE!"=="python" (
            for /f "delims=" %%I in ('py -3.14 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%I"
        )
        if "!PYTHON_EXE!"=="python" (
            if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
                set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
            ) else if exist "%ProgramFiles%\Python314\python.exe" (
                set "PYTHON_EXE=%ProgramFiles%\Python314\python.exe"
            )
        )
    )
)

:CLI_LOOP
echo Launching IntelliCodeX Interactive CLI...
if "%~1"=="" (
    "%PYTHON_EXE%" cli.py sample_repo --backend ollama --model qwen2.5-coder:7b --tui
) else (
    "%PYTHON_EXE%" cli.py %*
)

set "CLI_EXIT=!ERRORLEVEL!"
if not "!CLI_EXIT!"=="0" (
    echo.
    echo [ERROR] IntelliCodeX CLI exited with status code !CLI_EXIT!.
)
exit /b !CLI_EXIT!
