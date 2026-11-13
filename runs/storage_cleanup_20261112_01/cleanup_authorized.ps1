$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$donePath = Join-Path $PSScriptRoot 'deletion_completed.json'
if (Test-Path -LiteralPath $donePath) { throw 'Cleanup already completed; do not run twice.' }
$protection = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'data_protection_preflight.json') -Raw | ConvertFrom-Json
$preservation = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'preservation_before.json') -Raw | ConvertFrom-Json
if (-not $preservation.experiments.ok -or -not $preservation.archive.ok) { throw 'Preservation preflight failed.' }
foreach ($archive in $protection.archives_reverified) {
    if ((Get-FileHash -LiteralPath $archive.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $archive.sha256) { throw 'Project evidence archive changed.' }
}
$ledgerPath = Join-Path $projectRoot 'runs\test20_execution_20261111\batch_ledger.json'
if ((Get-FileHash -LiteralPath $ledgerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $protection.ledger_sha256) { throw 'Ledger changed.' }
$desktop = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('Docker Desktop','com.docker.backend') })
if ($desktop.Count -ne 0) { throw 'Docker Desktop must remain stopped.' }
$workers = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python' -and $_.CommandLine -match 'run_cf\.py|run_dev_supplement\.py|orchestrate\.py|score_run\.py|finish_cancelled_supplement\.py|swebench'
})
if ($workers.Count -ne 0) { throw 'Experiment workers remain.' }
$runningWsl = ((wsl --list --running --quiet) -join "`n") -replace "`0", ''
if ($LASTEXITCODE -ne 0 -or $runningWsl -match '(?m)^\s*docker-desktop\s*$') { throw 'Docker WSL is not confirmed stopped.' }

$activeRoot = 'D:\DockerData\swe-repair-20261111\DockerDesktopWSL'
$cacheRoot = 'D:\CodexExperimentCache\test20_20261111'
$cacheNames = @('official_oci_20261112','dependency_wheels','formal_compat_wheels_20261112',
    'mpl_compat_wheels_20261112_04','mpl_compat_wheels_20261112_05','requests_fixture_wheels_20261112',
    'requests_pytest_transitives_20261112_06','requests_pytest_transitives_20261112_07')
$targets = @($activeRoot,'E:\DockerBackups\swe-repair-20261111-pre-move','E:\DockerBackups\swe-repair-20261111-stopped')
foreach ($name in $cacheNames) { $targets += Join-Path $cacheRoot $name }
$allowed = @($targets | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') })
$settings = Get-Content -LiteralPath 'C:\Users\remil\AppData\Roaming\Docker\settings-store.json' -Raw | ConvertFrom-Json
if (-not [string]::Equals([IO.Path]::GetFullPath($settings.CustomWslDistroDir).TrimEnd('\'),$activeRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Docker configured data path differs.' }
$distros = @(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object {
    $v=Get-ItemProperty -LiteralPath $_.PSPath
    @{ Name=$v.DistributionName; BasePath=$v.BasePath; RegistryKey=$_.PSChildName }
})
$dockerDistro = @($distros | Where-Object { $_.Name -eq 'docker-desktop' })
if ($dockerDistro.Count -ne 1) { throw 'Expected exactly one Docker WSL registration.' }
$base = [string]$dockerDistro[0].BasePath
if ($base.StartsWith('\\?\')) { $base=$base.Substring(4) }
if (-not [string]::Equals([IO.Path]::GetFullPath($base).TrimEnd('\'),(Join-Path $activeRoot 'main'),[StringComparison]::OrdinalIgnoreCase)) { throw 'WSL registry path is outside the authorized data volume.' }
$rows = @()
foreach ($target in $targets) {
    $absolute = [IO.Path]::GetFullPath($target).TrimEnd('\')
    if ($absolute -notin $allowed) { throw 'Target outside literal allowlist.' }
    $item = Get-Item -LiteralPath $absolute -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unexpected target type or path link.' }
    $children = @(Get-ChildItem -LiteralPath $absolute -Recurse -Force)
    if (@($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -ne 0) { throw 'Linked descendant requires review.' }
    $files = @($children | Where-Object { -not $_.PSIsContainer })
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    $rows += @{ path=$absolute; file_count=$files.Count; logical_bytes=[long]$bytes;
        files=@($files | ForEach-Object { @{ path=$_.FullName; bytes=$_.Length; last_write_utc=$_.LastWriteTimeUtc.ToString('o') } }) }
}
$plan = @{ authorization=$protection.authorization; at=(Get-Date).ToString('o'); targets=$rows; wsl_registration=$dockerDistro[0];
    expected_image_count_removed=77; stopped_container_count_removed=1; preserve_cache_subdirs=@('source','checkpoint');
    project_archives_preserved=@($protection.archives_reverified | ForEach-Object { $_.path });
    free_before_bytes=@{ D=([IO.DriveInfo]::new('D')).AvailableFreeSpace; E=([IO.DriveInfo]::new('E')).AvailableFreeSpace } }
$planPath = Join-Path $PSScriptRoot 'deletion_plan.json'
if (Test-Path -LiteralPath $planPath) { throw 'Existing deletion plan; inspect partial progress rather than retry.' }
$plan | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $planPath -Encoding utf8
try {
    # Unregister only after verifying its BasePath is exactly the user-authorized D:\...\main.
    wsl --unregister docker-desktop
    if ($LASTEXITCODE -ne 0) { throw 'Docker WSL unregistration failed.' }
    @{ event='docker_wsl_unregistered'; at=(Get-Date).ToString('o'); authorized_base=$base } | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $PSScriptRoot 'deletion_events.jsonl') -Encoding utf8
    foreach ($target in $allowed) {
        $absolute = [IO.Path]::GetFullPath($target).TrimEnd('\')
        if ($absolute -notin $allowed) { throw 'Target no longer in exact allowlist.' }
        if (Test-Path -LiteralPath $absolute) {
            $current = Get-Item -LiteralPath $absolute -Force
            if ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Target changed into path link.' }
            Remove-Item -LiteralPath $absolute -Recurse -Force
        }
        if (Test-Path -LiteralPath $absolute) { throw 'Deletion incomplete.' }
        @{ event='authorized_target_deleted'; path=$absolute; at=(Get-Date).ToString('o') } | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $PSScriptRoot 'deletion_events.jsonl') -Encoding utf8
    }
    $registered = ((wsl --list --quiet) -join "`n") -replace "`0", ''
    if ($registered -match '(?m)^\s*docker-desktop\s*$') { throw 'Docker WSL still registered.' }
    foreach ($keep in @((Join-Path $cacheRoot 'source'),(Join-Path $cacheRoot 'checkpoint'))) {
        if (-not (Test-Path -LiteralPath $keep)) { throw 'Preserved source/checkpoint missing.' }
    }
    $after = @{ D=([IO.DriveInfo]::new('D')).AvailableFreeSpace; E=([IO.DriveInfo]::new('E')).AvailableFreeSpace }
    @{ at=(Get-Date).ToString('o'); status='authorized_deletions_complete'; deleted_targets=$allowed;
        logical_bytes_deleted=[long](($rows | Measure-Object -Property logical_bytes -Sum).Sum);
        free_before_bytes=$plan.free_before_bytes; free_after_bytes=$after;
        net_free_increase_bytes=@{ D=($after.D-$plan.free_before_bytes.D); E=($after.E-$plan.free_before_bytes.E) };
        docker_desktop_running=$false; docker_wsl_unregistered=$true; new_model_calls=0;
        cache_source_and_checkpoint_preserved=$true; project_zip_archives_preserved=$true
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $donePath -Encoding utf8
    Write-Output 'Authorized Docker data, two old VHDX backups, and image/dependency cache targets removed.'
} catch {
    @{ at=(Get-Date).ToString('o'); status='partial_cleanup_preserved_for_inspection'; error=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'deletion_failure.json') -Encoding utf8
    throw
}
