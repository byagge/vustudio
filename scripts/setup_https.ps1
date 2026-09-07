# HTTPS для панели VU Studio на Windows (Caddy → localhost:8080).
# Запуск от администратора:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_https.ps1 -Domain panel.example.com
#
# До этого в DNS: A-запись домена → публичный IP этой машины.

param(
    [Parameter(Mandatory = $true)]
    [string]$Domain
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BinDir = Join-Path $Root "bin"
$CaddyExe = Join-Path $BinDir "caddy.exe"
$Caddyfile = Join-Path $PSScriptRoot "Caddyfile"

$Domain = $Domain.Trim().ToLower() -replace "^https?://", "" -replace "/$", ""
if ($Domain -notmatch "\.") {
    throw "Укажите домен вида panel.example.com"
}

New-Item -ItemType Directory -Path $BinDir -Force | Out-Null

if (-not (Test-Path $CaddyExe)) {
    Write-Host "Скачиваю Caddy..."
    $zip = Join-Path $env:TEMP "caddy.zip"
    Invoke-WebRequest -Uri "https://github.com/caddyserver/caddy/releases/download/v2.10.0/caddy_2.10.0_windows_amd64.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $BinDir -Force
    Remove-Item $zip -Force
}

@(80, 443) | ForEach-Object {
    $name = "VU Studio HTTPS $_"
    if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $_ -Action Allow | Out-Null
        Write-Host "  [ok] брандмауэр: порт $_"
    }
}

$cf = @"
$Domain {
	encode gzip
	reverse_proxy 127.0.0.1:8080
}
"@
Set-Content -Path $Caddyfile -Value $cf -Encoding utf8
Write-Host "  [ok] Caddyfile → $Domain → 127.0.0.1:8080"

$action = New-ScheduledTaskAction -Execute $CaddyExe -Argument "run --config `"$Caddyfile`" --adapter caddyfile" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 365)
Register-ScheduledTask -TaskName "VuStudio-Caddy" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "VuStudio-Caddy"

Write-Host ""
Write-Host "Caddy запущен. Дальше:" -ForegroundColor Green
Write-Host "  1. DNS: A  $Domain  →  публичный IPv4 этой машины"
Write-Host "  2. В .env:  WEB_BASE_URL=https://$Domain"
Write-Host "  3. Restart-ScheduledTask -TaskName VuStudio-Bot"
Write-Host ""
Write-Host "Проверка через минуту: https://$Domain"
Write-Host "Лог: Get-ScheduledTask -TaskName VuStudio-Caddy"
