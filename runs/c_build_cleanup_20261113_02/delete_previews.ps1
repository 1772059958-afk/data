$ErrorActionPreference='Stop'
$project=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
$plan=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'cleanup_plan.json') -Raw | ConvertFrom-Json
if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'deletion_completed.json')){throw 'Already completed.'}
if(-not(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'protected_files_before.json'))){throw 'Protected snapshot missing.'}
$allowed=@('work','.chart-data-9ms2WV','.chart-data-uYclH4','.chart-data-wWZuBa','.chart-data-yKvtsO')
foreach($row in $plan.targets){
 $target=[IO.Path]::GetFullPath($row.absolute).TrimEnd('\')
 $expected=[IO.Path]::GetFullPath((Join-Path $project $row.relative)).TrimEnd('\')
 if($row.relative -notin $allowed -or -not [string]::Equals($target,$expected,[StringComparison]::OrdinalIgnoreCase) -or -not $target.StartsWith($project+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Target escaped authorized scope.'}
 $all=@(Get-Item -LiteralPath $target -Force)+@(Get-ChildItem -LiteralPath $target -Recurse -Force)
 if(@($all | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count){throw 'Linked path detected.'}
 $files=@($all | Where-Object {-not $_.PSIsContainer})
 if($files.Count -ne @($row.files).Count){throw 'Target changed after inventory.'}
 foreach($file in $row.files){
  $absolute=[IO.Path]::GetFullPath((Join-Path $project $file.path))
  if(-not $absolute.StartsWith($target+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Inventory escaped target.'}
  if((Get-FileHash -LiteralPath $absolute -Algorithm SHA256).Hash -ne $file.sha256){throw 'Build bytes changed.'}
 }
}
foreach($row in $plan.preserved){
 $keep=[IO.Path]::GetFullPath((Join-Path $project $row.preserved_path))
 if(-not $keep.StartsWith($PSScriptRoot+'\preserved_build_metadata\',[StringComparison]::OrdinalIgnoreCase)){throw 'Preserved file escaped audit.'}
 if((Get-FileHash -LiteralPath $keep -Algorithm SHA256).Hash -ne $row.sha256){throw 'Metadata not preserved.'}
}
$before=([IO.DriveInfo]::new('C')).AvailableFreeSpace
foreach($row in $plan.targets){Remove-Item -LiteralPath $row.absolute -Recurse -Force}
foreach($row in $plan.targets){if(Test-Path -LiteralPath $row.absolute){throw 'Deletion incomplete.'}}
$after=([IO.DriveInfo]::new('C')).AvailableFreeSpace
@{status='completed';at=(Get-Date).ToString('o');deleted_paths=@($plan.targets.absolute);deleted_logical_bytes=($plan.targets | Measure-Object bytes -Sum).Sum;free_C_change_bytes=($after-$before);shutdown=$false} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'deletion_completed.json') -Encoding utf8
Write-Output 'PPT previews and chart temporary directories deleted.'
