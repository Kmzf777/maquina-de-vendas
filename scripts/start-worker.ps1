$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

$env:PYTHONUNBUFFERED = "1"
Set-Location "$PSScriptRoot\..\backend"
. "$PSScriptRoot\stream-log.ps1"
Invoke-StreamLog -LogFilePath "$logsDir\worker.log" -Command {
    & "$PSScriptRoot\..\.venv\Scripts\python" -m app.campaign.worker
}
