<#
.SYNOPSIS
NASへの保管・読戻し検証を終えたB/C対象だけを削除します。
.DESCRIPTION
対象CSVと検証manifest、パス実体、更新日時、サイズ、未使用状態、保管物を確認し、個別削除します。
.INPUTS
bc-archive.json、10/17のdeletion-decisions.csv。
.OUTPUTS
bc-deletion.jsonl、bc-deletion-summary.json。失敗時は後続削除を停止します。
.EXAMPLE
powershell -NoProfile -File .workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/remove_bc.ps1
.NOTES
作成日: 2026-10-25
注意事項: 承認済みB/Cファイルの実削除を伴います。再帰削除・未検証ファイル削除はしません。
#>
$ErrorActionPreference = 'Stop'
$reportPath = Join-Path $PSScriptRoot 'bc-archive.json'
$report = [System.IO.File]::ReadAllText($reportPath) | ConvertFrom-Json
$nasManifest = '\\192.168.1.101\jra\jra-van-data\retired\pc-cleanup-20261025\manifest.json'
if ([System.IO.File]::ReadAllText($nasManifest) -ne [System.IO.File]::ReadAllText($reportPath)) { throw 'NAS manifest不一致' }
if ($report.status -ne 'archived_verified_not_deleted' -or $report.targets.Count -ne 74) { throw '保管完了状態・件数不一致' }
$rows = Import-Csv -LiteralPath (Join-Path $PSScriptRoot '..\storage-cleanup-20261017\deletion-decisions.csv')
$units = @($rows | Where-Object { $_.group -in @('B','C') } | ForEach-Object { $_.path })
$streams = [System.Collections.Generic.List[System.IO.FileStream]]::new()
$archiveStreams = [System.Collections.Generic.List[System.IO.FileStream]]::new()
$log = Join-Path $PSScriptRoot 'bc-deletion.jsonl'
if (Test-Path -LiteralPath $log) { throw '既存削除ログがあるため停止' }
$freeBefore = @{}
Get-PSDrive -Name C,D | ForEach-Object { $freeBefore[$_.Name] = $_.Free }
try {
    foreach ($obj in $report.objects) {
        $item = Get-Item -LiteralPath $obj.archive
        if ($item.Length -ne $obj.archive_bytes) { throw '保管物サイズ変化' }
        $archiveStreams.Add([System.IO.File]::Open($obj.archive, 'Open', 'Read', 'Read'))
    }
    foreach ($target in $report.targets) {
        $path = [System.IO.Path]::GetFullPath($target.path)
        if ($target.unit -notin $units -or $path -notin @($target.unit, ($target.unit+'-wal'), ($target.unit+'-shm'))) { throw '対象一覧外' }
        if ($path -ne $target.path) { throw '絶対パス正規化不一致' }
        $item = Get-Item -LiteralPath $path
        $expectedTicks = [long]([decimal]$target.identity.mtime_ns / 100) + 621355968000000000
        if ($item.Length -ne $target.identity.bytes -or $item.LastWriteTimeUtc.Ticks -ne $expectedTicks) { throw '元版変化' }
        $ancestor = $item
        while ($null -ne $ancestor) {
            if (($ancestor.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'reparse pointあり' }
            $ancestor = $ancestor.Parent
        }
        if (Test-Path -LiteralPath ($target.unit+'-journal')) { throw 'journalあり' }
        foreach ($suffix in @('-wal','-shm')) {
            $sidecar = $target.unit+$suffix
            if ((Test-Path -LiteralPath $sidecar) -and $sidecar -notin $report.targets.path) { throw '新規sidecarあり' }
        }
        $streams.Add([System.IO.File]::Open($path, 'Open', 'Read', 'None'))
    }
    for ($index=0; $index -lt $report.targets.Count; $index++) {
        $target = $report.targets[$index]
        $event = @{time_utc=[datetime]::UtcNow.ToString('o'); path=$target.path; bytes=$target.identity.bytes; event='before_remove'; archive=$target.archive}
        [System.IO.File]::AppendAllText($log, (($event | ConvertTo-Json -Compress)+"`n"), [System.Text.UTF8Encoding]::new($false))
        $streams[$index].Dispose()
        Remove-Item -LiteralPath $target.path -ErrorAction Stop
        if (Test-Path -LiteralPath $target.path) { throw '削除後の残存あり' }
        $event.event='removed'
        [System.IO.File]::AppendAllText($log, (($event | ConvertTo-Json -Compress)+"`n"), [System.Text.UTF8Encoding]::new($false))
    }
    $freeAfter = @{}
    Get-PSDrive -Name C,D | ForEach-Object { $freeAfter[$_.Name] = $_.Free }
    $summary = @{time_utc=[datetime]::UtcNow.ToString('o'); deleted_files=$report.targets.Count; logical_bytes=($report.targets.identity | Measure-Object bytes -Sum).Sum; free_before=$freeBefore; free_after=$freeAfter; nas_added_bytes=$report.nas_added_bytes}
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'bc-deletion-summary.json'), ($summary | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
    $summary | ConvertTo-Json -Depth 5
} finally {
    foreach ($stream in $streams) { $stream.Dispose() }
    foreach ($stream in $archiveStreams) { $stream.Dispose() }
}
