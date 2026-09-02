@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe vu-qa-bot\render_worker.py
pause
