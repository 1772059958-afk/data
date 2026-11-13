$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$auditDir = Join-Path $workspace 'runs\storage_maintenance_20261112_01'
$sourceRoot = 'D:\DockerBackups'
$targetRoot = 'E:\DockerBackups'
$blobRoot = 'D:\CodexExperimentCache\test20_20261111\official_oci_20261112\blobs\sha256'

function Write-NewJson($Path, $Value) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
        try { $writer.WriteLine(($Value | ConvertTo-Json -Depth 16)); $writer.Flush() }
        finally { $writer.Dispose() }
    } finally { $stream.Dispose() }
}

function Checked-Path([string]$Path, [string]$Root) {
    $full = [IO.Path]::GetFullPath($Path)
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if (-not ($full.Equals($base, [StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase))) {
        throw "Path escaped the explicitly authorized directory: $full"
    }
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing a reparse point: $cursor" }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $full
}

function Event($Phase, $Data) {
    $row = @{ at = [DateTimeOffset]::Now.ToString('o'); phase = $Phase; data = $Data }
    $line = $row | ConvertTo-Json -Compress -Depth 12
    [IO.File]::AppendAllText((Join-Path $auditDir 'events.jsonl'), $line + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output $line
}

function Prefix-Hash([string]$Path, [long]$Count) {
    $file = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $buffer = [byte[]]::new(8MB)
        $remaining = $Count
        while ($remaining -gt 0) {
            $wanted = [int][Math]::Min($buffer.Length, $remaining)
            $n = $file.Read($buffer, 0, $wanted)
            if ($n -eq 0) { throw 'Complete blob ended before the recorded partial length' }
            [void]$sha.TransformBlock($buffer, 0, $n, $buffer, 0)
            $remaining -= $n
        }
        [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
        return ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose(); $file.Dispose() }
}

if (Test-Path -LiteralPath $auditDir) { throw 'Audit tag already exists; do not repeat this operation blindly' }
[void](New-Item -ItemType Directory -Path $auditDir)
try {
    [void](Checked-Path $sourceRoot 'D:\DockerBackups')
    [void](Checked-Path $targetRoot 'E:\DockerBackups')
    [void](Checked-Path $blobRoot $blobRoot)
    $before = @('D','E') | ForEach-Object { $p = Get-PSDrive -Name $_; @{ drive = $_; free_bytes = $p.Free; used_bytes = $p.Used } }
    $volume = Get-Volume -DriveLetter E
    if ($volume.FileSystem -ne 'NTFS') { throw 'E target must be the checked NTFS volume' }
    $old = Get-Content -LiteralPath (Join-Path $workspace 'runs\test20_execution_20261111\migration\offline_backup_verified.json') -Raw | ConvertFrom-Json
    $stopped = Get-Content -LiteralPath (Join-Path $workspace 'runs\test20_execution_20261111\shutdown_audit.json') -Raw | ConvertFrom-Json
    $files = @()
    foreach ($entry in $old.files) { $files += @{ source = $entry.backup; expected_sha256 = $entry.sha256; expected_bytes = $entry.bytes } }
    foreach ($entry in $stopped.files) { $files += @{ source = $entry.checkpoint_backup; expected_sha256 = $entry.sha256; expected_bytes = $entry.size_bytes } }
    if ($files.Count -ne 4) { throw 'Expected exactly the four recorded cold-backup files' }
    $expectedPaths = @(
        'swe-repair-20261111-pre-move\disk\docker_data.vhdx', 'swe-repair-20261111-pre-move\main\ext4.vhdx',
        'swe-repair-20261111-stopped\disk\docker_data.vhdx', 'swe-repair-20261111-stopped\main\ext4.vhdx'
    )
    foreach ($row in $files) {
        $row.source = Checked-Path $row.source $sourceRoot
        $relative = [IO.Path]::GetRelativePath($sourceRoot, $row.source)
        if ($relative -notin $expectedPaths) { throw "Unapproved backup path: $relative" }
        $row.target = Checked-Path (Join-Path $targetRoot $relative) $targetRoot
        if (Test-Path -LiteralPath $row.target) { throw "Target already exists: $($row.target)" }
        $item = Get-Item -LiteralPath $row.source -Force
        if ($item.Length -ne $row.expected_bytes) { throw "Original backup size differs: $($row.source)" }
        $row.last_write_utc = $item.LastWriteTimeUtc.ToString('o')
    }
    foreach ($name in @('swe-repair-20261111-pre-move','swe-repair-20261111-stopped')) {
        $dir = Checked-Path (Join-Path $sourceRoot $name) $sourceRoot
        $all = @(Get-ChildItem -LiteralPath $dir -Force -Recurse)
        if (@($all | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'Reparse point in source backup' }
        if (@($all | Where-Object { -not $_.PSIsContainer }).Count -ne 2) { throw 'Unexpected files in source backup' }
        if (Test-Path -LiteralPath (Join-Path $targetRoot $name)) { throw 'Destination backup directory already exists' }
    }
    $total = ($files | Measure-Object -Property expected_bytes -Sum).Sum
    if ((Get-PSDrive -Name E).Free -lt ($total + 5GB)) { throw 'Insufficient E space including 5GiB reserve' }
    Write-NewJson (Join-Path $auditDir 'plan.json') @{ before = $before; backups = $files; backup_bytes = $total; active_Docker_data_moved = $false; no_models_or_Docker_started = $true }

    $names = @(
        '5e63a68ff6439b1581ee5ba0e3757810d61d5ad007e8033b5b5987df410e9537.partial',
        'd0e25e76b4c8bbe2eef78fe5856011818ea51b74783936282c6880e21f4bb5ec.partial02',
        'eea5d4fd085615b8743ec789b77b3152cc4c684814135864965d3e48199b48d3.partial02',
        'f03f14b9ae4ba4d73824ab87fea1d0e67aaf7bc9250481afb6273e5bdb8a28f6.partial'
    )
    $partials = @()
    foreach ($name in $names) {
        $path = Checked-Path (Join-Path $blobRoot $name) $blobRoot
        $digest = $name.Substring(0,64)
        $complete = Checked-Path (Join-Path $blobRoot $digest) $blobRoot
        $size = (Get-Item -LiteralPath $path).Length
        $ph = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ((Get-FileHash -LiteralPath $complete -Algorithm SHA256).Hash.ToLowerInvariant() -ne $digest) { throw 'Complete OCI blob SHA failed' }
        if ((Prefix-Hash $complete $size) -ne $ph) { throw 'Partial contains bytes not represented by the complete blob' }
        $partials += @{ path = $path; bytes = $size; sha256 = $ph; complete = $complete; complete_sha256 = $digest; exact_prefix_verified = $true }
    }
    Write-NewJson (Join-Path $auditDir 'partial_manifest.json') @{ files = $partials; reconstructable_from_complete_prefix = $true }
    foreach ($row in $partials) {
        [void](Checked-Path $row.path $blobRoot)
        if ((Get-FileHash -LiteralPath $row.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.sha256) { throw 'Partial changed before deletion' }
        Remove-Item -LiteralPath $row.path -ErrorAction Stop
        if (Test-Path -LiteralPath $row.path) { throw 'Partial deletion not confirmed' }
        Event 'partial_deleted' $row
    }

    foreach ($row in $files) {
        Event 'source_hash_start' @{ source = $row.source }
        $row.source_sha256 = (Get-FileHash -LiteralPath $row.source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($row.source_sha256 -ne $row.expected_sha256) { throw "Original cold backup SHA differs: $($row.source)" }
        [void](Checked-Path $row.target $targetRoot)
        $parent = Split-Path -Parent $row.target
        if (-not (Test-Path -LiteralPath $parent)) { [void](New-Item -ItemType Directory -Path $parent) }
        Event 'copy_start' @{ source = $row.source; target = $row.target; bytes = $row.expected_bytes }
        Copy-Item -LiteralPath $row.source -Destination $row.target -ErrorAction Stop
        Event 'copy_finished_hash_start' @{ target = $row.target }
        $row.target_sha256 = (Get-FileHash -LiteralPath $row.target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($row.target_sha256 -ne $row.source_sha256 -or (Get-Item -LiteralPath $row.target).Length -ne $row.expected_bytes) { throw 'Copied backup failed SHA/size validation; D original retained' }
        Event 'target_verified' $row
    }
    Write-NewJson (Join-Path $auditDir 'verified_targets.json') @{ files = $files; all_four_original_and_target_hashes_match = $true }
    Write-NewJson (Join-Path $targetRoot 'migration_20261112_01_verified.json') @{ files = $files; audit = $auditDir; all_four_original_and_target_hashes_match = $true }

    # Delete originals only after ALL E copies have passed the original historical SHAs.
    foreach ($row in $files) {
        [void](Checked-Path $row.source $sourceRoot)
        [void](Checked-Path $row.target $targetRoot)
        $sourceItem = Get-Item -LiteralPath $row.source
        if ($sourceItem.Length -ne $row.expected_bytes -or $sourceItem.LastWriteTimeUtc.ToString('o') -ne $row.last_write_utc) { throw 'Source changed during migration; refusing deletion' }
        if ((Get-Item -LiteralPath $row.target).Length -ne $row.expected_bytes) { throw 'Target changed after verification' }
    }
    foreach ($row in $files) {
        [void](Checked-Path $row.source $sourceRoot)
        Remove-Item -LiteralPath $row.source -ErrorAction Stop
        if (Test-Path -LiteralPath $row.source) { throw 'D original deletion not confirmed' }
        Event 'D_original_removed_after_verified_copy' @{ source = $row.source; target = $row.target; sha256 = $row.target_sha256 }
    }
    foreach ($name in @('swe-repair-20261111-pre-move','swe-repair-20261111-stopped')) {
        foreach ($suffix in @('disk','main','')) {
            $dir = Checked-Path (Join-Path (Join-Path $sourceRoot $name) $suffix) $sourceRoot
            if ((Test-Path -LiteralPath $dir) -and @(Get-ChildItem -LiteralPath $dir -Force).Count -eq 0) { Remove-Item -LiteralPath $dir }
        }
    }
    if ((Test-Path -LiteralPath $sourceRoot) -and @(Get-ChildItem -LiteralPath $sourceRoot -Force).Count -eq 0) { [void](Checked-Path $sourceRoot 'D:\DockerBackups'); Remove-Item -LiteralPath $sourceRoot }
    $after = @('D','E') | ForEach-Object { $p = Get-PSDrive -Name $_; @{ drive = $_; free_bytes = $p.Free; used_bytes = $p.Used } }
    $result = @{ kind = 'verified_cache_cleanup_and_cold_backup_relocation'; completed_at = [DateTimeOffset]::Now.ToString('o'); partials_deleted = $partials.Count; partial_bytes_reclaimed = ($partials | Measure-Object bytes -Sum).Sum; backup_files_moved = $files.Count; backup_bytes_moved = $total; backups = $files; before = $before; after = $after; active_Docker_data_moved = $false; models_or_Docker_started = $false; machine_shutdown_scheduled = $false }
    Write-NewJson (Join-Path $auditDir 'completed.json') $result
    Write-NewJson (Join-Path $targetRoot 'migration_20261112_01_completed.json') $result
    Event 'completed' @{ partials_deleted = 4; backup_files_moved = 4; after = $after }
} catch {
    Write-NewJson (Join-Path $auditDir 'failure.json') @{ at = [DateTimeOffset]::Now.ToString('o'); error = $_.Exception.Message; originals_deleted_only_after_all_targets_verified = $true }
    throw
}
