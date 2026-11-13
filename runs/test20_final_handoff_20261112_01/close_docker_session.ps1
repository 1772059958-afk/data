$ErrorActionPreference = 'Stop'
$auditPath = Join-Path $PSScriptRoot 'shutdown_audit.json'
if (Test-Path -LiteralPath $auditPath) { throw 'Preserve existing shutdown audit.' }
$workers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -match 'finish_cancelled_supplement\.py|score_run\.py.*devsupp_.*_eval|run_dev_supplement\.py|dev_supplement_20261112_02[\\/]orchestrate\.py'
})
if ($workers.Count -ne 0) { throw 'Owned experiment workers remain.' }
$containers = @(docker --context desktop-linux ps -a --format '{{json .}}' | ForEach-Object { $_ | ConvertFrom-Json })
if ($LASTEXITCODE -ne 0) { throw 'Cannot inventory containers.' }
$running = @($containers | Where-Object { $_.State -eq 'running' })
if ($running.Count -ne 0) { throw 'Running containers remain.' }
$images = @(docker --context desktop-linux image ls --no-trunc --format '{{json .}}' | ForEach-Object { $_ | ConvertFrom-Json })
if ($LASTEXITCODE -ne 0) { throw 'Cannot inventory images.' }
@{ containers=$containers; images=$images; at=(Get-Date).ToString('o') } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'docker_inventory_before_stop.json') -Encoding utf8
docker desktop stop
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop stop failed.' }
if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('Docker Desktop','com.docker.backend') }).Count -ne 0) { throw 'Docker processes still running.' }
$runningWsl = ((wsl --list --running --quiet) -join "`n") -replace "`0", ''
if ($runningWsl -match '(?m)^\s*docker-desktop\s*$') {
    wsl --terminate docker-desktop
    if ($LASTEXITCODE -ne 0) { throw 'Docker WSL termination failed.' }
    $runningWsl = ((wsl --list --running --quiet) -join "`n") -replace "`0", ''
}
if ($runningWsl -match '(?m)^\s*docker-desktop\s*$') { throw 'Docker WSL remains.' }
$dataPath = [IO.Path]::GetFullPath('D:\DockerData\swe-repair-20261111\DockerDesktopWSL')
$vhdx = @(Get-Item -LiteralPath (Join-Path $dataPath 'disk\docker_data.vhdx'), (Join-Path $dataPath 'main\ext4.vhdx') | ForEach-Object {
    @{ path=$_.FullName; size_bytes=$_.Length; last_write_utc=$_.LastWriteTimeUtc.ToString('o') }
})
@{ docker_desktop_stopped=$true; docker_wsl_running=$false;
    owned_running_containers_remaining=@(); owned_workers_remaining=@();
    stopped_containers_preserved=$containers; stopped_containers_preserved_count=$containers.Count;
    container_and_image_deletions=0; pre_stop_image_count=$images.Count;
    active_docker_data_path=$dataPath; active_cold_vhdx_files=$vhdx;
    new_full_vhdx_backup_created=$false; old_backups_are_not_current_full_volume=$true;
    project_evidence_archive_target='E:\DockerBackups\project-final-20261112-01';
    system_shutdown_requested_by_this_script=$false; at=(Get-Date).ToString('o')
} | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $auditPath -Encoding utf8
Write-Output 'Stopped Docker Desktop and Docker WSL; no running owned workers or containers. Stopped container evidence retained.'
