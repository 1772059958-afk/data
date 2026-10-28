# Repair the machine-level PATH, which on this PC is missing the standard
# Windows directories. Run once in an elevated PowerShell window:
#
#   Set-Location "C:\Users\MECH\Documents\Codex\2026-10-15\z\swe-repair"
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\scripts\fix_windows_path.ps1
#
# Existing entries are never removed or reordered. Missing standard Windows
# directories are prepended, and the previous value is saved to a file first so
# the change can be undone.

$ErrorActionPreference = 'Stop'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This script must run as Administrator." -ForegroundColor Red
    exit 1
}

$win = $env:SystemRoot
$required = @(
    (Join-Path $win 'System32'),
    $win,
    (Join-Path $win 'System32\Wbem'),
    (Join-Path $win 'System32\WindowsPowerShell\v1.0\'),
    (Join-Path $win 'System32\OpenSSH\')
)

$current = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($null -eq $current) { $current = '' }
$entries = @($current -split ';' | Where-Object { $_ -ne '' })

Write-Host "== current machine PATH ==" -ForegroundColor Cyan
$entries | ForEach-Object { Write-Host "  $_" }

$missing = @()
foreach ($dir in $required) {
    if (Test-Path -LiteralPath $dir) {
        $already = $entries | Where-Object { $_.TrimEnd('\') -ieq $dir.TrimEnd('\') }
        if (-not $already) { $missing += $dir }
    }
    else {
        Write-Host "  note: $dir does not exist on this PC, skipping" -ForegroundColor Yellow
    }
}

if (-not $missing) {
    Write-Host ""
    Write-Host "Nothing to add; the standard Windows directories are already present." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "== will prepend ==" -ForegroundColor Cyan
$missing | ForEach-Object { Write-Host "  $_" }

$backupDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts'
$backup = Join-Path $backupDir ("path_backup_{0}.txt" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
Set-Content -LiteralPath $backup -Value $current -Encoding UTF8
Write-Host ""
Write-Host "Old value saved to: $backup"

$new = (($missing + $entries) -join ';')
[Environment]::SetEnvironmentVariable('Path', $new, 'Machine')

Write-Host ""
Write-Host "== new machine PATH ==" -ForegroundColor Cyan
([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';') | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "Done. Open a NEW PowerShell window to pick it up (or just reboot, which you" -ForegroundColor Green
Write-Host "need to do for WSL anyway). Verify with:" -ForegroundColor Green
Write-Host "  (Get-Command wsl).Source"
