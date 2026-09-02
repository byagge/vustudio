@echo off
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"

echo ========================================
echo   VU Studio - start all services
echo   %ROOT%
echo ========================================
echo.

if not exist "%ROOT%\.env" goto noenv

if not exist "%ROOT%\.venv\Scripts\python.exe" goto mkvenv
goto startall

:mkvenv
echo Creating .venv...
python -m venv .venv
if errorlevel 1 goto nopython
"%ROOT%\.venv\Scripts\pip.exe" install -r "%ROOT%\requirements.txt"

:startall
if not exist "%ROOT%\queue\pending" mkdir "%ROOT%\queue\pending"
if not exist "%ROOT%\queue\processing" mkdir "%ROOT%\queue\processing"
if not exist "%ROOT%\queue\done" mkdir "%ROOT%\queue\done"
if not exist "%ROOT%\queue\failed" mkdir "%ROOT%\queue\failed"
if not exist "%ROOT%\output" mkdir "%ROOT%\output"

echo [1/4] API :8080
start "VU-API" cmd /k call "%ROOT%\scripts\run_api.cmd"
timeout /t 2 /nobreak >nul

echo [2/4] Portrait :8090
start "VU-Portrait" cmd /k call "%ROOT%\scripts\run_portrait.cmd"
timeout /t 2 /nobreak >nul

echo [3/4] Bot
start "VU-Bot" cmd /k call "%ROOT%\scripts\run_bot.cmd"
timeout /t 2 /nobreak >nul

echo [4/4] Worker
start "VU-Worker" cmd /k call "%ROOT%\scripts\run_worker.cmd"

echo.
echo Done. Open http://localhost:8080
echo Close all 4 windows to stop.
echo.
pause
exit /b 0

:noenv
echo ERROR: .env not found in %ROOT%
pause
exit /b 1

:nopython
echo ERROR: Python not found. Install Python 3.11+
pause
exit /b 1
