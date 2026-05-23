$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

Set-Location "$PSScriptRoot\..\backend"
docker compose up -d redis
. "$PSScriptRoot\stream-log.ps1"
Invoke-StreamLog -LogFilePath "$logsDir\redis.log" -Command {
    docker compose logs -f --no-log-prefix redis
}
