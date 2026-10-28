# Kept so that older notes still work. This name is misleading now: it no longer
# tries `wsl --install` (which needs the Microsoft Store delivery host, blocked
# on this network). It forwards to the two scripts that actually work here:
#
#   scripts/install_wsl_app.ps1   -> elevated, installs WSL from the official MSI
#   scripts/import_ubuntu.ps1     -> after the reboot, imports Ubuntu 24.04

$ErrorActionPreference = 'Stop'

Write-Host "This entry point moved. Running the current step 1." -ForegroundColor Yellow
Write-Host ""

& (Join-Path $PSScriptRoot 'install_wsl_app.ps1') @args
exit $LASTEXITCODE
