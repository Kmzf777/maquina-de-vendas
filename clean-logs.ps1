@('redis.log', 'backend.log', 'frontend.log') | ForEach-Object { 
  $logFile = "logs\$_"
  if (Test-Path $logFile) {
    Remove-Item $logFile -Force
  }
}
Write-Host "Logs limpos" -ForegroundColor Green
