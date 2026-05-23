$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

Set-Location "$PSScriptRoot\..\backend"
docker compose up -d redis
docker logs -f redis 2>&1 | Tee-Object -FilePath "$logsDir\redis.log" -Encoding UTF8
