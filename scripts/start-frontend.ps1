$port = 3000
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $conn.OwningProcess | Select-Object -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

Set-Location "$PSScriptRoot\..\frontend"
. "$PSScriptRoot\stream-log.ps1"
Invoke-StreamLog -LogFilePath "$logsDir\frontend.log" -Command {
    npm run dev -- --hostname 127.0.0.1 --port 3000
}
