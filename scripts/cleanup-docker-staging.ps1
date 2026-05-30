Write-Output 'Stopping possible Docker processes...'
Get-Process -Name 'Docker Desktop','com.docker.*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$p = 'C:\Program Files\Docker\Docker.staging'
if (Test-Path -LiteralPath $p) {
    Write-Output "Found staging path $p, attempting remove..."
    Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
    Write-Output 'Removed staging path.'
} else {
    Write-Output 'Staging path not found.'
}
