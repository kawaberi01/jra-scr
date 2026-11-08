<#
.SYNOPSIS
自分の専用研究監視だけをPIDとコマンド行で照合して停止する。
.DESCRIPTION
run台帳のPython PIDと実プロセスのscript/output引数が一致した場合だけ停止する。
.PARAMETER OutputDirectory
起動済み専用runの案件内相対パス。
.INPUTS
state.jsonとWindowsプロセス情報。
.OUTPUTS
停止記録worker-stop.jsonと状態。既存API/collectorは操作しない。
.EXAMPLE
rtk powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop_jra_research_shadow.ps1
.NOTES
作成日: 2026-11-07
注意事項: 未知PID/コマンド不一致は停止しない。自分の研究監視の更新用途。
#>
[CmdletBinding()]
param([string]$OutputDirectory = 'artifacts/jra_research/shadow_sessions_20261107_v3')
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$resolvedOutput = (Resolve-Path -LiteralPath (Join-Path $projectDirectory $OutputDirectory)).Path
$stateFile = Join-Path $resolvedOutput 'state.json'
$state = [IO.File]::ReadAllText($stateFile) | ConvertFrom-Json
$ownedPid = [int]$state.pid
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$ownedPid"
if ($null -eq $process -or -not $process.CommandLine.Contains('run_jra_research_shadow.py') -or
    -not $process.CommandLine.Contains($resolvedOutput)) {
    throw '専用runと一致する自分のプロセスを確認できないため停止しません。'
}
Stop-Process -Id $ownedPid -ErrorAction Stop
$state.status = 'stopped_for_payload_contract_fix'
[IO.File]::WriteAllText($stateFile, ($state | ConvertTo-Json -Depth 50), [Text.UTF8Encoding]::new($false))
$record = @{stopped_pid=$ownedPid; stopped_at=(Get-Date).ToUniversalTime().ToString('o'); reason='virtual_selection_list_contract'}
[IO.File]::WriteAllText((Join-Path $resolvedOutput 'worker-stop.json'), ($record | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$record | ConvertTo-Json
