$ErrorActionPreference = "Stop"

$wd = "D:\develop\jra-scr"
$stdout = Join-Path $wd ".workstate\logs\api\api_8000_stdout_restart.log"
$stderr = Join-Path $wd ".workstate\logs\api\api_8000_stderr_restart.log"
$listen = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

if ($listen) {
    $listen | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

$script = "Set-Location -LiteralPath '$wd'; rtk uv run uvicorn jra_srb.app:app --host 127.0.0.1 --port 8000 1>> '$stdout' 2>> '$stderr'"
Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", $script) -WorkingDirectory $wd -WindowStyle Hidden

Start-Sleep -Seconds 5
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
