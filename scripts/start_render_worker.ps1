# Render-worker на Windows VPS (Photoshop)
# Запуск: .\scripts\start_render_worker.ps1

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $Root "..")

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\pip install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "Создан .env — укажите PHOTOSHOP_EXE и пути к PSB"
}

$env:RENDER_MODE = "server"
Write-Host "Render-worker (Photoshop server mode)"
Write-Host "Queue: $((Get-Content .env | Select-String 'RENDER_QUEUE_DIR') -replace '.*=', '')"
Write-Host "Ctrl+C для остановки"

Set-Location vu-qa-bot
..\.venv\Scripts\python render_worker.py
