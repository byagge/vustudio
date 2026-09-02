# Полная установка VU Studio на Windows-сервер (одна машина).
# Запуск от администратора:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows_server.ps1
#
# Что делает:
#   1. venv + зависимости
#   2. Планировщик задач: API, Portrait API, бот, render worker
#   3. Правило брандмауэра для порта 8080

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Uvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"

Write-Host "=== VU Studio — установка на Windows-сервер ===" -ForegroundColor Cyan
Write-Host "Каталог: $Root`n"

# --- venv ---
if (-not (Test-Path $Python)) {
    Write-Host "Создаю виртуальное окружение..."
    python -m venv .venv
    & (Join-Path $Root ".venv\Scripts\pip.exe") install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") { Copy-Item ".env.example" ".env" }
    Write-Host "Создан .env — ОБЯЗАТЕЛЬНО заполните PHOTOSHOP_EXE и BOT_TOKEN" -ForegroundColor Yellow
}

# --- папки очереди ---
@("queue\pending", "queue\processing", "queue\done", "queue\failed", "output") | ForEach-Object {
    $p = Join-Path $Root $_
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

function Register-VuTask {
    param(
        [string]$Name,
        [string]$Exe,
        [string]$Args,
        [string]$WorkDir
    )
    $Action = New-ScheduledTaskAction -Execute $Exe -Argument $Args -WorkingDirectory $WorkDir
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 365)
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
    Start-ScheduledTask -TaskName $Name
    Write-Host "  [ok] $Name"
}

Write-Host "Регистрирую задачи Планировщика..."

Register-VuTask -Name "VuStudio-API" `
    -Exe $Uvicorn `
    -Args "api.main:app --host 0.0.0.0 --port 8080" `
    -WorkDir $Root

Register-VuTask -Name "VuStudio-Portrait" `
    -Exe $Uvicorn `
    -Args "portrait_api.app:app --host 0.0.0.0 --port 8090" `
    -WorkDir $Root

Register-VuTask -Name "VuStudio-Bot" `
    -Exe $Python `
    -Args "vu_qa_bot.py" `
    -WorkDir (Join-Path $Root "vu-qa-bot")

Register-VuTask -Name "VuStudio-Worker" `
    -Exe $Python `
    -Args "render_worker.py" `
    -WorkDir (Join-Path $Root "vu-qa-bot")

# --- firewall ---
$ruleName = "VU Studio API 8080"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow | Out-Null
    Write-Host "  [ok] Брандмауэр: порт 8080 открыт"
} else {
    Write-Host "  [--] Брандмауэр: правило уже есть"
}

Write-Host "`n=== Готово ===" -ForegroundColor Green
Write-Host @"

Проверьте .env (обязательно):
  PHOTOSHOP_EXE=C:\Program Files\Adobe\Adobe Photoshop 2024\Photoshop.exe
  WEB_BASE_URL=http://ВАШ_IP:8080
  API_KEY=случайный_секретный_ключ

Панель:    http://localhost:8080
Статус:    Get-ScheduledTask -TaskName 'VuStudio-*'
Worker:    powershell -File scripts\check_render_server.ps1

После установки Photoshop перезапустите worker:
  Restart-ScheduledTask -TaskName VuStudio-Worker

"@
