<#
Step 2 of 2: create the Ubuntu 24.04 distro inside the freshly installed WSL,
without going through the Microsoft Store.

`wsl --install -d Ubuntu` would download the distro from the Store delivery
host, which is unreachable here. Instead the official Ubuntu 24.04 WSL root
filesystem tarball is imported directly with `wsl --import`.

Needs no Administrator rights. Run after the reboot:

    Set-Location "C:\Users\MECH\Documents\Codex\2026-10-15\z\swe-repair"
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    .\scripts\import_ubuntu.ps1

The imported distro starts as root and has no password prompt; that is normal
for an imported tarball and is what the container setup needs.
#>

[CmdletBinding()]
param(
    [string] $Name = 'Ubuntu',
    [string] $InstallPath = 'C:\WSL\Ubuntu',
    [string] $Tarball = (Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor\ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz'),
    [string] $SumsPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor\SHA256SUMS')
)

$ErrorActionPreference = 'Stop'

function Write-Step($text) { Write-Host "== $text ==" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "   $text" -ForegroundColor Green }

$sys32 = Join-Path $env:SystemRoot 'System32'
$wsl = Join-Path $sys32 'wsl.exe'
if (-not (Test-Path -LiteralPath $wsl)) { throw "wsl.exe not found at $wsl" }

Write-Step 'checking WSL itself'
$version = & $wsl --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host $version
    throw 'wsl.exe is not functional yet. Reboot first, then run install_wsl_app.ps1 again if needed.'
}
$version | ForEach-Object { Write-Ok $_ }

Write-Step 'checking the root filesystem tarball'
if (-not (Test-Path -LiteralPath $Tarball)) { throw "tarball not found: $Tarball" }
$length = (Get-Item -LiteralPath $Tarball).Length
Write-Ok ("size: {0:N0} bytes" -f $length)

if (Test-Path -LiteralPath $SumsPath) {
    # The checksum file covers several artifacts; find the line for this file.
    $leaf = Split-Path -Leaf $Tarball
    $line = Get-Content -LiteralPath $SumsPath | Where-Object { $_ -match [regex]::Escape($leaf) } | Select-Object -First 1
    if ($line) {
        $expected = ($line -split '\s+')[0]
        Write-Step 'verifying sha256'
        $actual = (Get-FileHash -LiteralPath $Tarball -Algorithm SHA256).Hash
        if ($actual -ne $expected.ToUpper()) {
            throw "SHA256 mismatch.`n  expected: $expected`n  actual  : $actual"
        }
        Write-Ok "sha256 matches: $actual"
    } else {
        Write-Ok "no checksum line for $leaf in $SumsPath; skipping"
    }
} else {
    Write-Ok "no checksum file at $SumsPath; skipping verification"
}

Write-Step 'checking for an existing distro of that name'
$existing = (& $wsl --list --quiet 2>&1) | Where-Object { $_.Trim() -eq $Name }
if ($existing) {
    Write-Ok "a distro named '$Name' already exists; nothing to import"
} else {
    Write-Step "importing $Name into $InstallPath"
    New-Item -ItemType Directory -Force -Path $InstallPath | Out-Null
    & $wsl --import $Name $InstallPath $Tarball --version 2
    if ($LASTEXITCODE -ne 0) { throw "wsl --import failed with exit code $LASTEXITCODE" }
    Write-Ok 'import finished'
}

& $wsl --set-default $Name 2>&1 | Out-Null

Write-Step 'sanity check inside the distro'
& $wsl -d $Name -- bash -lc "cat /etc/os-release | head -n 2; echo kernel: \$(uname -r); echo cpus: \$(nproc); df -h / | tail -n 1"

Write-Host ''
Write-Host 'Next, inside Ubuntu:' -ForegroundColor Cyan
$repoRoot = Split-Path -Parent $PSScriptRoot
$drive = $repoRoot.Substring(0, 1).ToLower()
$rest = $repoRoot.Substring(2) -replace '\\', '/'
Write-Host "     sudo bash /mnt/$drive$rest/scripts/setup_docker_in_wsl.sh"
Write-Host ''
