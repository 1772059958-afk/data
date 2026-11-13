$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath('C:\Users\remil\Desktop\3yr\科研\proj\work').TrimEnd('\')
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
$expected = [IO.Path]::GetFullPath((Join-Path $project 'work')).TrimEnd('\')
if (-not [string]::Equals($target,$expected,[StringComparison]::OrdinalIgnoreCase)) { throw 'Target not the authorized project work directory.' }
$auditPath = Join-Path $PSScriptRoot 'build_deletion_completed.json'
if (Test-Path -LiteralPath $auditPath) { throw 'Cleanup already completed.' }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'work_retention_manifest.json') -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'protected_files_before.json'))) { throw 'Protected-file snapshot missing.' }
$item = Get-Item -LiteralPath $target -Force
if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unexpected work path type.' }
$children = @(Get-ChildItem -LiteralPath $target -Recurse -Force)
if (@($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -ne 0) { throw 'Linked paths detected.' }
$files = @($children | Where-Object { -not $_.PSIsContainer })
if ($files.Count -ne $manifest.original_work_files -or [long](($files | Measure-Object Length -Sum).Sum) -ne $manifest.original_work_logical_bytes) { throw 'Build files changed since preservation.' }
foreach ($row in $manifest.preserved_files) {
    $preserved = [IO.Path]::GetFullPath((Join-Path $project $row.preserved_path))
    $keepRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'preserved_work')) + '\'
    if (-not $preserved.StartsWith($keepRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Preserved source path outside audit directory.' }
    if ((Get-Item -LiteralPath $preserved).Length -ne $row.bytes) { throw 'Preserved source missing or truncated.' }
}
$before = ([IO.DriveInfo]::new('C')).AvailableFreeSpace
Remove-Item -LiteralPath $target -Recurse -Force
if (Test-Path -LiteralPath $target) { throw 'Build deletion incomplete.' }
$after = ([IO.DriveInfo]::new('C')).AvailableFreeSpace
@{ status='authorized_work_build_and_preview_cleanup_complete'; at=(Get-Date).ToString('o');
    deleted_absolute_path=$target; deleted_tree_logical_bytes=$manifest.original_work_logical_bytes;
    source_and_records_preserved_bytes=$manifest.preserved_logical_bytes;
    preserved_file_count=$manifest.preserved_files.Count;
    free_C_before_bytes=$before; free_C_after_bytes=$after; net_free_increase_bytes=($after-$before);
    no_experiment_or_model_execution=$true
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $auditPath -Encoding utf8
Write-Output 'Project work build tree removed; sources, input records and validation receipts preserved outside work.'
