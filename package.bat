@echo off
cd /d "%~dp0"

echo ============================================================
echo  AHNS SERP Tracker - Build Portable Package
echo ============================================================
echo.

REM Clean old output
if exist "SERP-Agent-Portable" rmdir /s /q "SERP-Agent-Portable"
mkdir "SERP-Agent-Portable"

REM Build exe
echo Building SERP-Agent.exe...
pyinstaller --onefile --name "SERP-Agent" ^
  app.py --distpath "SERP-Agent-Portable"

if not exist "SERP-Agent-Portable\SERP-Agent.exe" (
    echo ERROR: Build failed. Make sure pyinstaller is installed.
    echo Run: pip install pyinstaller
    pause
    exit /b 1
)

REM Copy templates + config next to exe
echo Copying templates...
xcopy /E /I /Q "templates" "SERP-Agent-Portable\templates"
if exist "config.json" copy "config.json" "SERP-Agent-Portable\config.json"

REM Create empty results folder
mkdir "SERP-Agent-Portable\results"

echo.
echo ============================================================
echo  DONE! Copy the folder "SERP-Agent-Portable" to any PC.
echo  Just double-click SERP-Agent.exe to run.
echo ============================================================
echo.
explorer "SERP-Agent-Portable"
pause
