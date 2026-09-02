@echo off
chcp 65001 >nul
setlocal

rem Упаковка проекта для сервера БЕЗ .venv, queue, output (меньше ложных срабатываний AV)
rem Запуск: scripts\pack_for_server.cmd
rem Результат: otris_server.zip в корне проекта

cd /d "%~dp0.."
set "ROOT=%CD%"
set "OUT=%ROOT%\otris_server.zip"

echo Упаковка: %ROOT%
echo Архив:   %OUT%
echo.

if exist "%OUT%" del /f "%OUT%"

powershell -NoProfile -Command ^
  "$root='%ROOT%';" ^
  "$exclude=@('.venv','queue','output','.history','__pycache__','.git','otris_server.zip','output.zip');" ^
  "$files=Get-ChildItem -Path $root -Recurse -File | Where-Object {" ^
  "  $rel=$_.FullName.Substring($root.Length+1);" ^
  "  -not ($exclude | Where-Object { $rel -like ('*'+$_+'*') -or $rel -like ($_+'*') })" ^
  "};" ^
  "Compress-Archive -Path ($files.FullName) -DestinationPath '%OUT%' -Force"

if errorlevel 1 (
    echo.
    echo PowerShell не сработал. Используйте RDP-копирование папки без .venv
    pause
    exit /b 1
)

echo.
echo Готово: %OUT%
echo Размер:
for %%A in ("%OUT%") do echo   %%~zA bytes
echo.
echo На сервере после распаковки:
echo   cd C:\Users\admin\Desktop\otris
echo   python -m venv .venv
echo   .venv\Scripts\pip install -r requirements.txt
echo   scripts\start_all.cmd
echo.
pause
