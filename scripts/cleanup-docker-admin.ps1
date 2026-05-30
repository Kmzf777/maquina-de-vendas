Write-Output 'Stopping Docker processes...'
Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -like 'Docker*' -or
    $_.Name -like 'com.docker*' -or
    $_.Name -like 'vpnkit*' -or
    $_.Name -like 'kubectl*' -or
    $_.Name -like 'mutagen*'
} | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Output 'Stopping Docker services...'
Get-Service -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -like 'com.docker*' -or
    $_.DisplayName -like 'Docker*'
} | ForEach-Object {
    if ($_.Status -ne 'Stopped') {
        Stop-Service -Name $_.Name -Force -ErrorAction SilentlyContinue
    }
}

function Remove-AdminPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Output "Not found: $Path"
        return
    }

    Write-Output "Taking ownership: $Path"
    takeown /f "$Path" /r /d y | Out-Host
    icacls "$Path" /grant "$env:USERNAME`:(OI`)(CI`)F" /t /c | Out-Host
    Write-Output "Removing: $Path"
    cmd /c "rmdir /s /q \"$Path\"" | Out-Host
}

Remove-AdminPath -Path 'C:\Program Files\Docker'
Remove-AdminPath -Path 'C:\ProgramData\DockerDesktop'
Remove-AdminPath -Path 'C:\ProgramData\Docker'

Write-Output 'Removing user-level Docker folders...'
$userPaths = @()
$userPaths += (Join-Path $env:LOCALAPPDATA 'Docker')
$userPaths += (Join-Path $env:LOCALAPPDATA 'Docker Desktop')
$userPaths += (Join-Path $env:APPDATA 'Docker')
$userPaths += (Join-Path $env:USERPROFILE '.docker')
$userPaths += (Join-Path $env:USERPROFILE 'AppData\Roaming\Docker')
$userPaths += (Join-Path $env:USERPROFILE 'AppData\Local\Docker')
$userPaths += (Join-Path $env:USERPROFILE 'AppData\Local\Docker Desktop')
$userPaths += (Join-Path $env:USERPROFILE 'AppData\Local\DockerDesktop')

foreach ($userPath in $userPaths) {
    if (Test-Path -LiteralPath $userPath) {
        Remove-Item -LiteralPath $userPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Output 'Docker admin cleanup complete.'