# Запуск API + бота (локально, два окна)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $Root "..")

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\pip install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "Создан .env — заполните BOT_TOKEN и ALLOWED_USERS"
}

Write-Host "API: http://localhost:8080"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\..'; .\.venv\Scripts\uvicorn api.main:app --reload --port 8080"

Start-Sleep -Seconds 2
Write-Host "Bot: vu_qa_bot.py"
Set-Location vu-qa-bot
..\.venv\Scripts\python vu_qa_bot.py
