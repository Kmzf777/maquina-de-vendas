$port = 8001
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $conn.OwningProcess | Select-Object -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

$env:PYTHONUNBUFFERED = "1"
Set-Location "$PSScriptRoot\..\backend"
. "$PSScriptRoot\stream-log.ps1"
Invoke-StreamLog -LogFilePath "$logsDir\backend.log" -Command {
    & "$PSScriptRoot\..\.venv\Scripts\python" -m uvicorn app.main:app --host 0.0.0.0 --port 8001
}
