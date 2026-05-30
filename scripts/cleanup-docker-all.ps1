function Remove-IfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (Test-Path -LiteralPath $Path) {
        Write-Output "Removing $Path"
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Output "Failed to remove ${Path}: $($_.Exception.Message)"
            Write-Output "If this is under Program Files, rerun these commands from an elevated PowerShell:"
            Write-Output "takeown /f `"$Path`" /r /d y"
            Write-Output "icacls `"$Path`" /grant $env:USERNAME`:(OI`)(CI`)F /t /c"
            Write-Output "rmdir /s /q `"$Path`""
        }
    } else {
        Write-Output "Not found: $Path"
    }
}

Write-Output 'Stopping Docker processes...'
$processes = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -like 'Docker*' -or
    $_.Name -like 'com.docker*' -or
    $_.Name -like 'vpnkit*' -or
    $_.Name -like 'kubectl*' -or
    $_.Name -like 'mutagen*'
}

if ($processes) {
    $processes | Stop-Process -Force -ErrorAction SilentlyContinue
}

Write-Output 'Stopping Docker services...'
$services = Get-Service -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -like 'com.docker*' -or
    $_.DisplayName -like 'Docker*'
}

foreach ($service in $services) {
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name $service.Name -Force -ErrorAction SilentlyContinue
    }
}

Write-Output 'Removing Docker folders...'
 $paths = @()
$paths += 'C:\Program Files\Docker'
$paths += 'C:\Program Files (x86)\Docker'
$paths += 'C:\ProgramData\Docker'
$paths += 'C:\ProgramData\DockerDesktop'
$paths += 'C:\ProgramData\Docker Desktop'
$paths += (Join-Path $env:LOCALAPPDATA 'Docker')
$paths += (Join-Path $env:LOCALAPPDATA 'Docker Desktop')
$paths += (Join-Path $env:APPDATA 'Docker')
$paths += (Join-Path $env:USERPROFILE '.docker')
$paths += (Join-Path $env:USERPROFILE 'AppData\Roaming\Docker')
$paths += (Join-Path $env:USERPROFILE 'AppData\Local\Docker')
$paths += (Join-Path $env:USERPROFILE 'AppData\Local\Docker Desktop')
$paths += (Join-Path $env:USERPROFILE 'AppData\Local\DockerDesktop')

foreach ($path in $paths) {
    Remove-IfExists -Path $path
}

Write-Output 'Removing Docker shortcuts if present...'
$shortcuts = @()
$shortcuts += (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Docker Desktop')
$shortcuts += (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Docker Desktop')

foreach ($shortcutPath in $shortcuts) {
    Remove-IfExists -Path $shortcutPath
}

Write-Output 'Docker cleanup complete.'