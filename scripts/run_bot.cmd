@echo off
cd /d "%~dp0.."
set PYTHONUNBUFFERED=1
echo Starting VU bot (console). Close this window to stop.
.venv\Scripts\python.exe -u vu-qa-bot\vu_qa_bot.py
pause
