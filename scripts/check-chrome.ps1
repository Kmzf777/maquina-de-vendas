$chromeExe = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path -LiteralPath $chromeExe)) {
    Write-Output "Missing: $chromeExe"
    exit 1
}

try {
    & $chromeExe --version 2>&1 | ForEach-Object { Write-Output $_ }
} catch {
    Write-Output $_.Exception.Message
    exit 1
}