<#
.SYNOPSIS
JRAの当日収集を毎日9時に起動するWindowsタスクを登録します。
.DESCRIPTION
概要: 既存登録をバックアップし、日次タスクの確認後に旧週末タスクを無効化します。
入力: なし。既存タスクのログオン方式と設定を引き継ぎます。
出力: JRA-SRB-Odds-Daily、旧タスクXML、登録結果の標準出力。
.INPUTS
なし。
.OUTPUTS
日次タスクの登録内容と次回実行時刻を表示します。
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\register_jra_odds_daily_task.ps1"
.NOTES
作成日: 2026-10-12。
注意事項: ローカルWindowsタスクを変更します。実行中タスクは変更せず中止します。
タスクを開始する処理はありません。バックアップは案件内task-backupsへ保存します。
#>
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$taskName = "JRA-SRB-Odds-Daily"
$oldNames = @("JRA-SRB-Odds-Weekly-Saturday", "JRA-SRB-Odds-Weekly-Sunday")
$oldTasks = @(Get-ScheduledTask -TaskPath "\" -TaskName $oldNames -ErrorAction SilentlyContinue)
$dailyTask = Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue
$tasks = @($oldTasks)
if ($null -ne $dailyTask) { $tasks += $dailyTask }
if (@($tasks | Where-Object { $_.State -eq "Running" }).Count -gt 0) {
    throw "収集タスクが実行中です。停止せず切替を中止します。"
}
if ((Get-TimeZone).Id -ne "Tokyo Standard Time") {
    throw "Windowsタイムゾーンが日本時間ではありません。9時設定を確認してください。"
}
$scriptPath = Join-Path $PSScriptRoot "run_jra_odds_timeline_today.ps1"
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) { throw "収集スクリプトがありません。" }
$backupDir = Join-Path $root (".workstate\jra-srb\jra-daily-collection\task-backups\{0}" -f (Get-Date -Format "yyyyMMdd_HHmmssfff"))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
foreach ($task in $tasks) {
    $xml = Export-ScheduledTask -TaskPath $task.TaskPath -TaskName $task.TaskName
    [IO.File]::WriteAllText((Join-Path $backupDir "$($task.TaskName).xml"), $xml, [Text.Encoding]::Unicode)
}
$action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $scriptPath) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At "09:00"
if ($oldTasks.Count -gt 0) {
    $principal = $oldTasks[0].Principal
    $settings = $oldTasks[0].Settings
    $settings.Enabled = $true
    $settings.MultipleInstances = 2 # IgnoreNew
    $settings.StartWhenAvailable = $true
}
else {
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 10)
}
$definition = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "毎日9時に公式開催一覧を確認し、開催日の出馬表・オッズを時点収集。非開催日は正常終了。"
Register-ScheduledTask -TaskPath "\" -TaskName $taskName -InputObject $definition -Force | Out-Null
$registered = Get-ScheduledTask -TaskPath "\" -TaskName $taskName
if (-not $registered.Settings.Enabled -or $registered.Triggers[0].CimClass.CimClassName -ne "MSFT_TaskDailyTrigger" -or $registered.Triggers[0].DaysInterval -ne 1 -or $registered.Actions[0].Arguments -notmatch [regex]::Escape($scriptPath)) {
    throw "日次タスク登録内容の確認に失敗しました。旧タスクは無効化しません。"
}
foreach ($task in $oldTasks) {
    Disable-ScheduledTask -TaskPath $task.TaskPath -TaskName $task.TaskName | Out-Null
}
Write-Output "backup_dir=$backupDir"
$registered | Select-Object TaskName,State | Format-List
Get-ScheduledTaskInfo -TaskPath "\" -TaskName $taskName | Select-Object NextRunTime | Format-List
