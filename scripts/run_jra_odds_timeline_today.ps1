param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$targetDate = Get-Date -Format "yyyy-MM-dd"
$logDir = Join-Path $root ".workstate\logs"
$log = Join-Path $logDir "jra_odds_timeline_$($targetDate.Replace('-', ''))_stdout.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $root

$arguments = @(
    "uv", "run", "jra-srb", "collect-jra-odds-timeline",
    "--date", $targetDate,
    "--courses", "all",
    "--bet-types", "win,quinella,wide,trio",
    "--offset-minutes", "30,10,2",
    "--bet-type-offsets", "win=30,10,2;quinella=30,10,2;wide=30,10,2;trio=10,2",
    "--db", "data/db/analysis.sqlite",
    "--poll-seconds", "15",
    "--min-interval-seconds", "1",
    "--max-lateness-seconds", "120",
    "--max-live-requests", "432"
)
if ($DryRun) {
    $arguments += "--dry-run"
}

& rtk @arguments 2>&1 | Tee-Object -FilePath $log -Append
exit $LASTEXITCODE
