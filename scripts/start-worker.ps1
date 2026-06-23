$logsDir = "$PSScriptRoot\..\logs"
New-Item -ItemType Directory -Force $logsDir | Out-Null

$env:PYTHONUNBUFFERED = "1"

# --- Blindagem da .venv: garante o ambiente isolado antes de subir o worker ---
$venvActivate = "$PSScriptRoot\..\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    Write-Host "ERRO: .venv nao encontrada. Crie com 'python -m venv .venv' e rode 'pip install -r backend/requirements.txt'." -ForegroundColor Red
    exit 1
}
. $venvActivate

Set-Location "$PSScriptRoot\..\backend"
. "$PSScriptRoot\stream-log.ps1"
Invoke-StreamLog -LogFilePath "$logsDir\worker.log" -Command {
    & "$PSScriptRoot\..\.venv\Scripts\python" -m app.campaign.worker
}
