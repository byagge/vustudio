# HTTPS front for VU Studio on Windows: Caddy -> 127.0.0.1:8080
# Run as Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_https.ps1 -Domain photoshop.arix.vu
#
# DNS first: A record of the domain -> this machine public IPv4.

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
    throw "Domain must look like panel.example.com"
}

New-Item -ItemType Directory -Path $BinDir -Force | Out-Null

if (-not (Test-Path $CaddyExe)) {
    Write-Host "Downloading Caddy..."
    $zip = Join-Path $env:TEMP "caddy.zip"
    Invoke-WebRequest -Uri "https://github.com/caddyserver/caddy/releases/download/v2.10.0/caddy_2.10.0_windows_amd64.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $BinDir -Force
    Remove-Item $zip -Force
}

@(80, 443) | ForEach-Object {
    $name = "VU Studio HTTPS $_"
    if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $_ -Action Allow | Out-Null
        Write-Host "  [ok] firewall port $_"
    }
}

$lines = @(
    "$Domain {",
    "    encode gzip",
    "    reverse_proxy 127.0.0.1:8080",
    "}"
)
[System.IO.File]::WriteAllLines($Caddyfile, $lines)
Write-Host "  [ok] Caddyfile $Domain -> 127.0.0.1:8080"

$caddyArgs = "run --config `"$Caddyfile`" --adapter caddyfile"
$action = New-ScheduledTaskAction -Execute $CaddyExe -Argument $caddyArgs -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$taskSettings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 365)
Register-ScheduledTask -TaskName "VuStudio-Caddy" -Action $action -Trigger $trigger -Settings $taskSettings -Force | Out-Null
Start-ScheduledTask -TaskName "VuStudio-Caddy"

Write-Host ""
Write-Host "Caddy started. Next:" -ForegroundColor Green
Write-Host "  1. DNS A $Domain -> this VPS public IPv4"
Write-Host "  2. In .env set WEB_BASE_URL=https://$Domain"
Write-Host "  3. Restart-ScheduledTask -TaskName VuStudio-Bot"
Write-Host ""
Write-Host "Open in a minute: https://$Domain"
Write-Host "Task: Get-ScheduledTask -TaskName VuStudio-Caddy"
