<#
.SYNOPSIS
日本時間の当日のJRA出馬表・オッズ時系列を収集します。
.DESCRIPTION
概要: 開催一覧を確認する既存CLIを起動し、非開催日は正常終了します。
入力: DryRunスイッチ。uvはユーザー領域またはPATHから解決します。
出力: 選択backendの分析DB、実行別UTF-8ログ、子プロセス終了コード。
.PARAMETER DryRun
取得予定を出力し、出馬表・オッズを取得保存しません。
.INPUTS
なし。
.OUTPUTS
標準出力に実行記録のパスを表示します。
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_jra_odds_timeline_today.ps1" -DryRun
.NOTES
作成日: 不明。
注意事項: 本収集は外部通信とDB追記を行います。DryRunも開催一覧へ通信します。
取得上限は当日の開催・券種・取得時点から収集本体が自動算出します。
同じスクリプトの実行を排他します。PCの停止中は収集できません。
#>
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$japanNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time")
$targetDate = $japanNow.ToString("yyyy-MM-dd")
$runTag = "{0}_{1}_{2}" -f $japanNow.ToString("yyyyMMdd"), $japanNow.ToString("HHmmssfff"), $PID
$logDir = Join-Path $root ".workstate\logs"
$stateDir = Join-Path $root ".workstate\jra-srb\jra-daily-collection"
New-Item -ItemType Directory -Force -Path $logDir, $stateDir | Out-Null
$runLog = Join-Path $logDir "jra_odds_timeline_${runTag}_run.log"
$stdoutLog = Join-Path $logDir "jra_odds_timeline_${runTag}_stdout.log"
$stderrLog = Join-Path $logDir "jra_odds_timeline_${runTag}_stderr.log"
$lockPath = Join-Path $stateDir "collector.lock"
$lockStream = $null
$exitCode = 1
$previousUtf8 = $env:PYTHONUTF8
$previousUnbuffered = $env:PYTHONUNBUFFERED

try {
    Add-Content -LiteralPath $runLog -Encoding UTF8 -Value "started_at=$($japanNow.ToString('o')) date=$targetDate dry_run=$DryRun"
    Write-Output "run_log=$runLog"
    try {
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    }
    catch [IO.IOException] {
        # 共有違反だけを重複起動として扱い、ディスク等の障害は外側へ伝える。
        if (($_.Exception.HResult -band 0xFFFF) -notin @(32, 33)) { throw }
        Add-Content -LiteralPath $runLog -Encoding UTF8 -Value "status=skipped_already_running exit_code=0"
        exit 0
    }

    $userUv = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".local\bin\uv.exe"
    if (Test-Path -LiteralPath $userUv -PathType Leaf) {
        $uvPath = $userUv
    }
    else {
        $uvPath = (Get-Command uv.exe -CommandType Application -ErrorAction Stop).Source
    }
    $arguments = @(
        "run", "--frozen", "jra-srb", "collect-jra-odds-timeline",
        "--date", $targetDate,
        "--courses", "all",
        "--bet-types", "win,quinella,wide,trio",
        "--offset-minutes", "30,10,2",
        "--bet-type-offsets", "win=30,10,2;quinella=30,10,2;wide=30,10,2;trio=10,2",
        "--db", ('"{0}"' -f (Join-Path $root "data\db\analysis.sqlite")),
        "--poll-seconds", "15",
        "--min-interval-seconds", "1",
        "--max-lateness-seconds", "120"
    )
    if ($DryRun) { $arguments += "--dry-run" }
    $env:PYTHONUTF8 = "1"
    $env:PYTHONUNBUFFERED = "1"
    Add-Content -LiteralPath $runLog -Encoding UTF8 -Value "uv=$uvPath stdout=$stdoutLog stderr=$stderrLog"
    # stderrをPowerShellの停止例外へ変換せず、子プロセス終了コードで判定する。
    $process = Start-Process -FilePath $uvPath -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -Wait -PassThru
    $exitCode = $process.ExitCode
    Add-Content -LiteralPath $runLog -Encoding UTF8 -Value "finished_at=$((Get-Date).ToString('o')) exit_code=$exitCode"
}
catch {
    Add-Content -LiteralPath $runLog -Encoding UTF8 -Value "status=failed error=$($_.Exception.Message) exit_code=1"
    Write-Warning $_.Exception.Message
    $exitCode = 1
}
finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
    $env:PYTHONUTF8 = $previousUtf8
    $env:PYTHONUNBUFFERED = $previousUnbuffered
}
exit $exitCode
