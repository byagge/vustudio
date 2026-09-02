@echo off
cd /d "%~dp0.."
.venv\Scripts\uvicorn.exe portrait_api.app:app --host 0.0.0.0 --port 8090
