@echo off
chcp 65001 >nul
setlocal

rem Запуск всего проекта одной командой (CMD, без PowerShell)
rem   cd C:\Users\admin\Desktop\otris\scripts
rem   start_all.cmd

cd /d "%~dp0.."
set "ROOT=%CD%"

echo ========================================
echo   VU Studio - запуск всех сервисов
echo   %ROOT%
echo ========================================
echo.

if not exist "%ROOT%\.env" (
    echo [ОШИБКА] Нет файла .env в %ROOT%
    pause
    exit /b 1
)

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [INFO] Создаю .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ОШИБКА] Python не найден
        pause
        exit /b 1
    )
    call "%ROOT%\.venv\Scripts\pip.exe" install -r "%ROOT%\requirements.txt"
)

if not exist "%ROOT%\queue\pending" mkdir "%ROOT%\queue\pending"
if not exist "%ROOT%\queue\processing" mkdir "%ROOT%\queue\processing"
if not exist "%ROOT%\queue\done" mkdir "%ROOT%\queue\done"
if not exist "%ROOT%\queue\failed" mkdir "%ROOT%\queue\failed"
if not exist "%ROOT%\output" mkdir "%ROOT%\output"

echo [1/4] API + панель :8080
start "VU-API" cmd /k call "%ROOT%\scripts\run_api.cmd"

timeout /t 2 /nobreak >nul

echo [2/4] Portrait API :8090
start "VU-Portrait" cmd /k call "%ROOT%\scripts\run_portrait.cmd"

timeout /t 2 /nobreak >nul

echo [3/4] Telegram-бот
start "VU-Bot" cmd /k call "%ROOT%\scripts\run_bot.cmd"

timeout /t 2 /nobreak >nul

echo [4/4] Render worker
start "VU-Worker" cmd /k call "%ROOT%\scripts\run_worker.cmd"

echo.
echo ========================================
echo   Готово. Открыты 4 окна:
echo   VU-API / VU-Portrait / VU-Bot / VU-Worker
echo.
echo   Панель: http://localhost:8080
echo   Остановка: закройте все 4 окна
echo ========================================
echo.
pause
