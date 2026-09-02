@echo off
cd /d "%~dp0.."
.venv\Scripts\uvicorn.exe api.main:app --host 0.0.0.0 --port 8080
pause
