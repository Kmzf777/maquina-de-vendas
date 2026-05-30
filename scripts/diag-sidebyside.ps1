$ErrorActionPreference = 'SilentlyContinue'

Write-Output '=== Visual C++ runtimes ==='
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' |
    Where-Object { $_.DisplayName -match 'Visual C\+\+|Microsoft Visual C\+\+|VC\+\+' } |
    Select-Object DisplayName, DisplayVersion, Publisher |
    Sort-Object DisplayName |
    Format-Table -AutoSize |
    Out-String -Width 240 |
    Write-Output

Write-Output '=== Pinned Chrome shortcut ==='
$lnk = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Google Chrome.lnk'
if (Test-Path -LiteralPath $lnk) {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    [pscustomobject]@{
        TargetPath = $shortcut.TargetPath
        Arguments = $shortcut.Arguments
        WorkingDirectory = $shortcut.WorkingDirectory
        IconLocation = $shortcut.IconLocation
    } | Format-List | Out-String -Width 240 | Write-Output
} else {
    Write-Output 'Shortcut not found.'
}

Write-Output '=== Recent SideBySide events ==='
Get-WinEvent -LogName Application |
    Where-Object { $_.ProviderName -eq 'SideBySide' -or $_.Message -match 'side by side|side-by-side|sxstrace' } |
    Select-Object -First 10 TimeCreated, ProviderName, Id, LevelDisplayName, Message |
    Format-List |
    Out-String -Width 240 |
    Write-Output