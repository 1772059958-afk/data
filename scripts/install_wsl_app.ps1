#Requires -RunAsAdministrator
<#
Step 1 of 2 for this machine: enable the two Windows features and install the
WSL application from the official MSI.

Why not `wsl --install`: that command fetches the package through the Microsoft
Store delivery host (tlu.dl.delivery.mp.microsoft.com), which is unreachable on
this network -- it aborted at 4.5% the first time. The MSI is the same official
package, published on the WSL GitHub release page, and it can be fetched through
the local proxy instead.

Run in an ELEVATED PowerShell:

    Set-Location "C:\Users\MECH\Documents\Codex\2026-10-15\z\swe-repair"
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    .\scripts\install_wsl_app.ps1

Then reboot, and run .\scripts\import_ubuntu.ps1 (that one does not need
Administrator).
#>

[CmdletBinding()]
param(
    [string] $MsiPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor\wsl.3.0.3.0.x64.msi'),
    [string] $ExpectedSha256 = 'AE977286974255BD26BF925F00F40F5692C6B2084155CBC0563C09AEA091F211',
    [string] $LogPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'vendor\wsl_msi_install.log'),
    [switch] $SkipFeatureCheck
)

$ErrorActionPreference = 'Stop'

function Write-Step($text) { Write-Host "== $text ==" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "   $text" -ForegroundColor Green }
function Write-Warn2($text) { Write-Host "   $text" -ForegroundColor Yellow }

$sys32 = Join-Path $env:SystemRoot 'System32'
$dism = Join-Path $sys32 'dism.exe'
$msiexec = Join-Path $sys32 'msiexec.exe'
$wslExe = Join-Path $sys32 'wsl.exe'

Write-Step 'preflight'
foreach ($tool in @($dism, $msiexec)) {
    if (-not (Test-Path -LiteralPath $tool)) {
        throw "Cannot find $tool. This Windows installation looks damaged; stop here."
    }
}
if (-not (Test-Path -LiteralPath $MsiPath)) {
    throw "MSI not found: $MsiPath`nDownload it first (see README, 'vendor' section)."
}
Write-Ok "MSI: $MsiPath"

if (-not $SkipFeatureCheck) {
    Write-Step 'enabling Windows features (WSL + VirtualMachinePlatform)'
    & $dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
    $dism1 = $LASTEXITCODE
    & $dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart | Out-Null
    $dism2 = $LASTEXITCODE
    Write-Ok "dism exit codes: $dism1, $dism2   (0 = already enabled, 3010 = reboot required)"
    if ($dism1 -notin 0, 3010 -or $dism2 -notin 0, 3010) {
        throw "Enabling the optional features failed (exit codes $dism1, $dism2)."
    }
} else {
    Write-Warn2 'feature check skipped on request'
}

Write-Step 'verifying the installer before running it'
$signature = Get-AuthenticodeSignature -LiteralPath $MsiPath
if ($signature.Status -ne 'Valid') {
    throw "Installer signature is not valid: $($signature.Status) - $($signature.StatusMessage)"
}
if ($signature.SignerCertificate.Subject -notlike '*Microsoft Corporation*') {
    throw "Installer is signed by an unexpected publisher: $($signature.SignerCertificate.Subject)"
}
Write-Ok "signature valid, signer: Microsoft Corporation"

$actual = (Get-FileHash -LiteralPath $MsiPath -Algorithm SHA256).Hash
if ($actual -ne $ExpectedSha256) {
    throw "SHA256 mismatch.`n  expected: $ExpectedSha256`n  actual  : $actual"
}
Write-Ok "sha256 matches: $actual"

Write-Step 'installing (this takes a minute and prints nothing while it works)'
$arguments = @('/i', "`"$MsiPath`"", '/qn', '/norestart', '/L*v', "`"$LogPath`"")
$process = Start-Process -FilePath $msiexec -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
$code = $process.ExitCode
if ($code -notin 0, 3010) {
    Write-Warn2 "msiexec exit code $code; log: $LogPath"
    throw "Installation failed with exit code $code."
}
Write-Ok "msiexec exit code $code (0 = success, 3010 = success and reboot required)"

Write-Step 'result'
$rebootPending = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')
Write-Ok ("reboot pending: " + $rebootPending)
if (Test-Path -LiteralPath $wslExe) {
    & $wslExe --version 2>&1 | ForEach-Object { Write-Ok $_ }
}

Write-Host ''
Write-Host 'Next:' -ForegroundColor Cyan
Write-Host '  1. Reboot Windows (required: the VM platform service only appears after a reboot).'
Write-Host '  2. Back in a normal PowerShell:' -ForegroundColor Cyan
Write-Host '       cd "C:\Users\MECH\Documents\Codex\2026-10-15\z\swe-repair"'
Write-Host '       .\scripts\import_ubuntu.ps1'
Write-Host '  3. Then, inside Ubuntu, run scripts/setup_docker_in_wsl.sh as described there.'
Write-Host ''
