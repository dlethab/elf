# Opens the FICTIONAL sample archive (the real archive is not touched).
#   .\run-sample.ps1            this computer only: http://127.0.0.1:5001 (with the debugger)
#   .\run-sample.ps1 -Lan       also phones and other devices on the same Wi-Fi (no debugger: it must never be reachable from other devices)
#   .\run-sample.ps1 -Rebuild   start the sample over
# Accounts and password: instance\sample-accounts.txt
param([switch]$Rebuild, [switch]$Lan, [int]$Port = 5001)
Set-Location $PSScriptRoot
if ($Rebuild -or -not (Test-Path "instance\sample.db")) {
    .\.venv\Scripts\flask.exe --app elf_archive sample-db
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
    .\.venv\Scripts\flask.exe --app elf_archive run --host 0.0.0.0 --port $Port
} else {
    Write-Host "Open http://127.0.0.1:$Port (Ctrl+C to stop)"
    .\.venv\Scripts\flask.exe --app elf_archive run --debug --port $Port
}
