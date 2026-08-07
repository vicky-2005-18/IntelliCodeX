@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
if exist "..\venv\Scripts\activate.bat" call ..\venv\Scripts\activate.bat
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat
if exist "..\.venv\Scripts\activate.bat" call ..\.venv\Scripts\activate.bat

echo Starting IntelliCodeX FastAPI Backend on http://localhost:8000 ...
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
pause
