# Opens the FICTIONAL sample archive with the PHP edition (the real archive is not touched).
#   .\run-sample.ps1            this computer only: http://127.0.0.1:8001
#   .\run-sample.ps1 -Lan       also phones and other devices on the same Wi-Fi
#   .\run-sample.ps1 -Rebuild   start the sample over
#   .\run-sample.ps1 -Port 8080 another port
# Accounts and password: instance\sample-accounts.txt
param([switch]$Rebuild, [switch]$Lan, [int]$Port = 8001)
Set-Location $PSScriptRoot
$php = if (Test-Path "tools\php\php.exe") { "tools\php\php.exe" } else { "php" }
if (-not (Get-Command $php -ErrorAction SilentlyContinue)) {
    Write-Host "PHP was not found. Install PHP 8.1 or newer, or put a portable PHP in tools\php (see README)."
    exit 1
}
$env:ELF_ENV = "development"
if ($Rebuild -or -not (Test-Path "instance\sample.db")) {
    & $php bin\elf sample-db
    if (-not $?) { exit 1 }
}
Write-Host ""
Get-Content "instance\sample-accounts.txt" | Select-String -Pattern "password:" | ForEach-Object { Write-Host $_.Line }
Write-Host "(accounts: instance\sample-accounts.txt)"
$env:ELF_DATABASE_PATH = "instance\sample.db"
$env:ELF_MEDIA_ROOT = "instance\sample-media"
if ($Lan) {
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.InterfaceAlias -notmatch 'vEthernet|Loopback|VirtualBox|VMware' } |
        Select-Object -ExpandProperty IPAddress
    Write-Host ""
    Write-Host "On your phone (same Wi-Fi), open:"
    foreach ($ip in $ips) { Write-Host "  http://${ip}:$Port" }
    Write-Host "On this computer: http://127.0.0.1:$Port   (Ctrl+C to stop)"
    Write-Host "If the phone cannot connect, allow the port through Windows Firewall (see README)."
    $env:ELF_BASE_URL = if ($ips) { "http://$(@($ips)[0]):$Port" } else { "http://127.0.0.1:$Port" }
    & $php -S "0.0.0.0:$Port" -t public public/index.php
} else {
    Write-Host "Open http://127.0.0.1:$Port (Ctrl+C to stop)"
    $env:ELF_BASE_URL = "http://127.0.0.1:$Port"
    & $php -S "127.0.0.1:$Port" -t public public/index.php
}
