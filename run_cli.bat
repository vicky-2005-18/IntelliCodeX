@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
if exist "..\venv\Scripts\activate.bat" call ..\venv\Scripts\activate.bat
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat
if exist "..\.venv\Scripts\activate.bat" call ..\.venv\Scripts\activate.bat

echo Running IntelliCodeX Interactive CLI (Ollama)...
python cli.py sample_repo --backend ollama
pause
