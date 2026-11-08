<#
.SYNOPSIS
固定候補の当日仮想検証を非表示の一回限りの子プロセスで開始する。
.DESCRIPTION
既存の専用runを確認し、二重起動を避けてuvを開始し、起動PIDとログを保存する。
.PARAMETER OutputDirectory
protocol.jsonとstate.jsonが確認済みの専用run。既存の起動記録は上書きしない。
.PARAMETER TargetDate
監視日。指定日の18時JSTにPython側で停止する。
.INPUTS
確認済みrun、uv、共通SQL設定。
.OUTPUTS
起動PID、worker-launch.json、標準出力/標準エラーログ。
.EXAMPLE
rtk powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_jra_research_shadow.ps1
.NOTES
作成日: 2026-11-07
注意事項: 実購入なし。恒久タスク登録・既存API/collector再起動なし。
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = 'artifacts/jra_research/shadow_sessions_20261107_v3',
    [string]$TargetDate = '2026-11-07'
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$resolvedOutput = (Resolve-Path -LiteralPath (Join-Path $projectDirectory $OutputDirectory)).Path
if (-not $resolvedOutput.StartsWith($projectDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw '専用runは案件フォルダー内に必要です。'
}
$launchFile = Join-Path $resolvedOutput 'worker-launch.json'
if (Test-Path -LiteralPath $launchFile) {
    throw '起動記録が既にあります。二重起動を避けるためPIDと状態を確認してください。'
}
foreach ($requiredFile in @('protocol.json', 'state.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedOutput $requiredFile))) {
        throw "一巡確認済みの専用runが必要です: $requiredFile"
    }
}
$uvPath = (Get-Command uv -ErrorAction Stop).Source
$arguments = @('run', '--frozen', '--extra', 'ml', 'python', '-X', 'utf8',
    'scripts/run_jra_research_shadow.py', '--date', $TargetDate, '--output', ('"' + $resolvedOutput + '"'))
$shadowProcess = Start-Process -FilePath $uvPath -ArgumentList $arguments -WorkingDirectory $projectDirectory `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $resolvedOutput 'worker.stdout.log') `
    -RedirectStandardError (Join-Path $resolvedOutput 'worker.stderr.log') -PassThru
$launch = @{
    launcher_pid = $shadowProcess.Id
    started_at = (Get-Date).ToUniversalTime().ToString('o')
    target_date = $TargetDate
    stop_at = ($TargetDate + 'T18:00:00+09:00')
    script = 'scripts/run_jra_research_shadow.py'
}
[IO.File]::WriteAllText($launchFile, ($launch | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Start-Sleep -Seconds 1
if ($shadowProcess.HasExited) {
    throw '監視プロセスが終了しました。worker.stderr.logを確認してください。'
}
$shadowProcess | Select-Object Id, ProcessName
