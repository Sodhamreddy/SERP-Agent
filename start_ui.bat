@echo off
cd /d "%~dp0"

echo ============================================================
echo  AHNS SERP Tracker - Web UI
echo ============================================================
echo.

REM 1. Portable python_runtime folder (highest priority)
if exist "%~dp0python_runtime\python.exe" (
    set PYTHON=%~dp0python_runtime\python.exe
    goto :found
)

REM 2. Common Python install locations
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
    goto :found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
    goto :found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
    goto :found
)
if exist "C:\Python312\python.exe" (
    set PYTHON=C:\Python312\python.exe
    goto :found
)
if exist "C:\Python311\python.exe" (
    set PYTHON=C:\Python311\python.exe
    goto :found
)

REM 3. Try PATH
where python >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python
    goto :found
)
where py >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py
    goto :found
)

echo ERROR: Python not found on this machine.
echo Please install Python from https://www.python.org
pause
exit /b 1

:found
echo Using Python: %PYTHON%
echo.

REM Kill any existing process on port 5000
echo Checking for existing server on port 5000...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr "127.0.0.1:5000 " ^| findstr "LISTENING"') do (
    echo   Stopping old process PID %%a ...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM Prevent laptop sleep while agent runs
echo Disabling sleep while agent runs...
powercfg /change standby-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /change monitor-timeout-dc 0

echo Starting server...
echo Open: http://localhost:5000
echo Keep this window open. Press Ctrl+C to stop.
echo.

%PYTHON% app.py

REM Restore default sleep settings when agent stops
echo Restoring sleep settings...
powercfg /change standby-timeout-ac 30
powercfg /change standby-timeout-dc 15
powercfg /change monitor-timeout-dc 10
pause
