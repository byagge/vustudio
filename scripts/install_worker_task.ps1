#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows: установка render_worker как задачи Планировщика (task4 §9.2).

Запуск от администратора:
  powershell -ExecutionPolicy Bypass -File scripts\install_worker_task.ps1
"""
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Worker = Join-Path $Root "vu-qa-bot\render_worker.py"
$TaskName = "OtrisRenderWorker"

if (-not (Test-Path $Python)) {
    Write-Error "Сначала создайте venv: python -m venv .venv && pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Write-Host "Создан .env — заполните PHOTOSHOP_EXE и пути к PSB"
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Worker`"" -WorkingDirectory (Join-Path $Root "vu-qa-bot")
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Task '$TaskName' registered and started."
Write-Host "Check: Get-ScheduledTask -TaskName $TaskName"
Write-Host "Logs: python scripts/check_render_server.ps1 (from project root)"
