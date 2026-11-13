$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$auditPath = Join-Path $PSScriptRoot 'shutdown_audit.json'
if (Test-Path -LiteralPath $auditPath) { throw 'Shutdown audit already exists; preserve it.' }
$workers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -match 'test20_resume_20261112_02[\\/](continue_formal|resume_B_remaining|complete_formal_scoring|recover_interrupted_B8)\.py' -or
    $_.CommandLine -match 'run_cf\.py.*--tag\s+test20_[ABCDE]_20261112_0[12]' -or
    $_.CommandLine -match 'score_run\.py.*test20_[ABCDE]_20261112_0[12]'
})
if ($workers.Count -ne 0) { throw 'Owned experimental workers remain active; finish/reconcile them first.' }
$containers = @(docker --context desktop-linux ps -a --format '{{json .}}' | ForEach-Object { $_ | ConvertFrom-Json })
if ($LASTEXITCODE -ne 0) { throw 'Cannot inventory Docker containers.' }
# Normal completion should have removed its own containers. Any remaining
# container is preserved for inspection; no global pruning or forced removal.
if ($containers.Count -ne 0) { throw 'Containers remain; perform scoped reconciliation before stopping Docker.' }
$images = @(docker --context desktop-linux image ls --no-trunc --format '{{json .}}' | ForEach-Object { $_ | ConvertFrom-Json })
if ($LASTEXITCODE -ne 0) { throw 'Cannot inventory current images.' }
$preStop = @{ containers=$containers; images=$images; at=(Get-Date).ToString('o') }
$preStop | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'docker_inventory_before_stop.json') -Encoding utf8
docker desktop stop
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop stop failed.' }
$dockerRunning = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('Docker Desktop','com.docker.backend') })
if ($dockerRunning.Count -ne 0) { throw 'Docker processes still running after graceful stop.' }
$runningWsl = ((wsl --list --running --quiet) -join "`n") -replace "`0", ''
if ($runningWsl -match '(?m)^\s*docker-desktop\s*$') {
    wsl --terminate docker-desktop
    if ($LASTEXITCODE -ne 0) { throw 'Docker-specific WSL termination failed.' }
    $runningWsl = ((wsl --list --running --quiet) -join "`n") -replace "`0", ''
}
if ($runningWsl -match '(?m)^\s*docker-desktop\s*$') { throw 'docker-desktop WSL still running.' }
$dataPath = [IO.Path]::GetFullPath('D:\DockerData\swe-repair-20261111\DockerDesktopWSL')
if (-not (Test-Path -LiteralPath $dataPath)) { throw 'Expected active data path missing.' }
$vhdx = @(Get-Item -LiteralPath (Join-Path $dataPath 'disk\docker_data.vhdx'), (Join-Path $dataPath 'main\ext4.vhdx') | ForEach-Object {
    @{ path=$_.FullName; size_bytes=$_.Length; last_write_utc=$_.LastWriteTimeUtc.ToString('o') }
})
$audit = @{ docker_desktop_stopped=$true; docker_wsl_running=$false;
    owned_containers_remaining=@(); owned_workers_remaining=@();
    pre_stop_container_count=$containers.Count; pre_stop_image_count=$images.Count;
    active_docker_data_path=$dataPath; active_cold_vhdx_files=$vhdx;
    old_backup_locations=@('E:\DockerBackups\swe-repair-20261111-pre-move','E:\DockerBackups\swe-repair-20261111-stopped');
    old_backups_are_not_current_full_volume=$true; new_full_vhdx_backup_created=$false;
    project_evidence_archive_target='E:\DockerBackups\project-session-20261112-02';
    system_shutdown_requested_by_this_script=$false; at=(Get-Date).ToString('o') }
$audit | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $auditPath -Encoding utf8
Write-Output 'Docker Desktop and its WSL distribution stopped; no experimental workers or containers remain.'
