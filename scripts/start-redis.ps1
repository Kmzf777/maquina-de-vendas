$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

Set-Location "$PSScriptRoot\..\backend"

# --- Alerta de Docker: se o daemon estiver fechado, avisa de forma amigavel ---
# Checagem por exit code: comandos nativos (docker) nao lancam excecao capturavel
# por try/catch no PowerShell, entao testamos $LASTEXITCODE do `docker info`.
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: O Docker Desktop parece estar fechado. Por favor, abra-o antes de iniciar os servicos!" -ForegroundColor Red
    exit 1
}

docker compose up -d redis
. "$PSScriptRoot\stream-log.ps1"
Invoke-StreamLog -LogFilePath "$logsDir\redis.log" -Command {
    docker compose logs -f --no-log-prefix redis
}
