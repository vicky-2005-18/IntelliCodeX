@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
if exist "..\venv\Scripts\activate.bat" call ..\venv\Scripts\activate.bat
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat
if exist "..\.venv\Scripts\activate.bat" call ..\.venv\Scripts\activate.bat

echo Launching IntelliCodeX Interactive CLI...
if "%~1"=="" (
    python cli.py sample_repo --backend ollama
) else (
    python cli.py %*
)
pause

