<#
.SYNOPSIS
期限付きの前向き比較をHiddenプロセスで一回起動する。
.DESCRIPTION
日付・モデル・実装のcheck-onlyを先に実行し、起動PIDとログを保存する。
.PARAMETER OutputDirectory
未作成の専用成果物フォルダー。
.PARAMETER ResumeFrom
停止済み監督runを同一候補・同一予想IDのまま新runへ移行する場合だけ指定する。
.INPUTS
固定済みspec454/455、uv、共通SQL設定、既存APIと収集。
.OUTPUTS
監督PID、起動ログ、日別原本、3候補の仮想集計。
.EXAMPLE
rtk powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_jra_shadow_series.ps1
.NOTES
作成日: 2026-11-07
注意事項: 実購入0円。2026-11-21の18時JSTに停止。恒久タスク・API再起動なし。
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = 'artifacts/jra_research/shadow_series_20261108_20261121',
    [string]$ResumeFrom = ''
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$targetDirectory = [IO.Path]::GetFullPath((Join-Path $projectDirectory $OutputDirectory))
$researchDirectory = Join-Path $projectDirectory 'artifacts\jra_research'
if (-not $targetDirectory.StartsWith($researchDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw '専用成果物フォルダーは研究配下に必要です。'
}
if (Test-Path -LiteralPath $targetDirectory) { throw '既存の監督runがあります。二重起動を拒否します。' }
$uvPath = (Get-Command uv -ErrorAction Stop).Source
Push-Location -LiteralPath $projectDirectory
try {
    & $uvPath run --frozen --extra ml python -X utf8 scripts/run_jra_shadow_series.py --check-only
    if ($LASTEXITCODE -ne 0) { throw '起動前確認に失敗しました。' }
} finally { Pop-Location }
$logPrefix = $targetDirectory + '.supervisor'
if ((Test-Path -LiteralPath ($logPrefix + '.stdout.log')) -or (Test-Path -LiteralPath ($logPrefix + '.stderr.log'))) {
    throw '既存の監督ログがあります。起動状況を確認してください。'
}
$arguments = @('run', '--frozen', '--extra', 'ml', 'python', '-X', 'utf8',
    'scripts/run_jra_shadow_series.py', '--output', ('"' + $targetDirectory + '"'))
if ($ResumeFrom) {
    $sourceDirectory = (Resolve-Path -LiteralPath (Join-Path $projectDirectory $ResumeFrom)).Path
    $arguments += @('--resume-from', ('"' + $sourceDirectory + '"'))
}
$seriesProcess = Start-Process -FilePath $uvPath -ArgumentList $arguments -WorkingDirectory $projectDirectory `
    -WindowStyle Hidden -RedirectStandardOutput ($logPrefix + '.stdout.log') `
    -RedirectStandardError ($logPrefix + '.stderr.log') -PassThru
Start-Sleep -Seconds 3
if ($seriesProcess.HasExited) { throw '監督処理が終了しました。stderrを確認してください。' }
$launch = @{ launcher_pid = $seriesProcess.Id; started_at = (Get-Date).ToUniversalTime().ToString('o');
             output = $targetDirectory; stop_at = '2026-11-21T18:00:00+09:00' }
[IO.File]::WriteAllText(($logPrefix + '.launch.json'), ($launch | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$seriesProcess | Select-Object Id, ProcessName
