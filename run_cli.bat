@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
if exist "..\venv\Scripts\activate.bat" call ..\venv\Scripts\activate.bat
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat
if exist "..\.venv\Scripts\activate.bat" call ..\.venv\Scripts\activate.bat

:CLI_LOOP
echo Launching IntelliCodeX Interactive CLI...
if "%~1"=="" (
    python cli.py sample_repo --backend ollama
) else (
    python cli.py %*
)

echo.
echo =======================================================================
echo IntelliCodeX CLI has stopped.
echo =======================================================================
set "RESTART_CLI=Y"
set /p "RESTART_CLI=Restart CLI? [Y/N] (default Y): "
if /i "%RESTART_CLI%"=="N" goto :CLI_EXIT
echo.
goto :CLI_LOOP

:CLI_EXIT
exit /b 0

