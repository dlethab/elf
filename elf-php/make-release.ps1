# Builds a copy of the PHP edition ready to upload to a web host: dist\elf-php\ and dist\elf-php.zip.
# Leaves out what never belongs on a server: tools\ (the Windows PHP), instance\ (local databases, uploads,
# the sample), tests\, development scripts and development-only libraries (PHPUnit).
#   .\make-release.ps1
Set-Location $PSScriptRoot
$php = if (Test-Path "tools\php\php.exe") { "tools\php\php.exe" } else { "php" }
$out = "dist\elf-php"
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($item in "bin", "migrations", "public", "src", "templates", "translations", "docs", "composer.json", "composer.lock",
                  ".env.example", ".htaccess", "README.md") {
    Copy-Item -Recurse $item "$out\$item"
}
New-Item -ItemType Directory -Force "$out\instance" | Out-Null
Set-Content "$out\instance\.htaccess" "Require all denied" -Encoding ascii
# production libraries only, with an optimised class map
& $php tools\composer.phar install --working-dir=$out --no-dev --optimize-autoloader --no-interaction --quiet
if (-not $?) { Write-Host "composer failed"; exit 1 }
Compress-Archive -Path $out -DestinationPath "dist\elf-php.zip" -Force
$size = [math]::Round((Get-Item "dist\elf-php.zip").Length / 1MB, 1)
Write-Host "Ready to upload: dist\elf-php.zip ($size MB). See docs\DEPLOYMENT.md."
