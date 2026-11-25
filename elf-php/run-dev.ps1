# Runs the archive on this computer for development, with its own database (instance\archive.db by default,
# or whatever ELF_DATABASE_PATH says in .env). Pending database updates are applied at start-up in development.
#   .\run-dev.ps1               http://127.0.0.1:8000
#   .\run-dev.ps1 -Port 8080
param([int]$Port = 8000)
Set-Location $PSScriptRoot
$php = if (Test-Path "tools\php\php.exe") { "tools\php\php.exe" } else { "php" }
if (-not $env:ELF_ENV) { $env:ELF_ENV = "development" }
$env:ELF_BASE_URL = "http://127.0.0.1:$Port"
Write-Host "Open http://127.0.0.1:$Port (Ctrl+C to stop). Queued email can be read at /dev/outbox."
& $php -S "127.0.0.1:$Port" -t public public/index.php
