@echo off
setlocal enabledelayedexpansion

TITLE IntelliCodeX GitHub Auto-Sync

:: Navigate to project directory
cd /d "%~dp0"

echo =======================================================================
echo                   INTELLICODEX GITHUB AUTO-UPDATER
echo =======================================================================
echo.

:: Verify git is installed
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed or not in system PATH.
    echo Please install Git and try again.
    pause
    exit /b 1
)

:: Get current branch name
set CURRENT_BRANCH=main
for /f "delims=" %%i in ('git branch --show-current 2^>nul') do set CURRENT_BRANCH=%%i
if "!CURRENT_BRANCH!"=="" set CURRENT_BRANCH=main

echo Active Branch: !CURRENT_BRANCH!
echo Repository:    https://github.com/vicky-2005-18/IntelliCodeX.git
echo.

:: Show modified/untracked files
echo Checking local status:
echo -----------------------------------------------------------------------
git status -s
echo -----------------------------------------------------------------------
echo.

:: Prompt for commit message
set COMMIT_MSG=
set /p COMMIT_MSG="Enter commit message (Leave blank for default timestamp): "

if "!COMMIT_MSG!"=="" (
    set COMMIT_MSG=Auto-update IntelliCodeX (%DATE% %TIME:~0,8%)
)

echo.
echo [1/3] Staging all modified and new files...
git add .

echo [2/3] Committing changes...
git commit -m "!COMMIT_MSG!"
if %errorlevel% neq 0 (
    echo.
    echo Note: No new changes detected to commit or commit skipped.
)

echo [3/3] Pushing updates to GitHub (!CURRENT_BRANCH!)...
git push origin !CURRENT_BRANCH!

echo.
if %errorlevel% equ 0 (
    echo =======================================================================
    echo SUCCESS: Code successfully updated on GitHub!
    echo Branch: !CURRENT_BRANCH!
    echo Message: "!COMMIT_MSG!"
    echo =======================================================================
) else (
    echo =======================================================================
    echo ERROR: Failed to push to GitHub.
    echo Please check your network connection or GitHub authentication.
    echo =======================================================================
)

echo.
pause
