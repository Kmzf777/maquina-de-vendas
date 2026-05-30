$paths = @()
$paths += 'C:\Program Files\Docker'
$paths += 'C:\Program Files\Docker Desktop'
$paths += 'C:\ProgramData\DockerDesktop'
$paths += 'C:\ProgramData\Docker'
$paths += (Join-Path $env:LOCALAPPDATA 'Docker')
$paths += (Join-Path $env:LOCALAPPDATA 'Docker Desktop')
$paths += 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$paths += 'C:\Program Files\Docker\Docker\DockerCli.exe'
$paths += 'C:\Program Files\Docker\Docker\frontend\Docker Desktop.exe'

foreach ($path in $paths) {
    if (Test-Path -LiteralPath $path) {
        Write-Output "FOUND: $path"
        if ((Get-Item -LiteralPath $path).PSIsContainer) {
            Get-ChildItem -LiteralPath $path -Name -ErrorAction SilentlyContinue | Select-Object -First 10 | ForEach-Object { Write-Output "  $_" }
        }
    } else {
        Write-Output "MISSING: $path"
    }
}