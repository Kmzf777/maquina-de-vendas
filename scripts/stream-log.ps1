function Invoke-StreamLog {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,

        [Parameter(Mandatory = $true)]
        [string]$LogFilePath
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.IO.StreamWriter]::new($LogFilePath, $false, $encoding)

    try {
        & $Command 2>&1 | ForEach-Object {
            $line = $_.ToString()
            Write-Host $line
            $writer.WriteLine($line)
            $writer.Flush()
        }
    }
    finally {
        $writer.Dispose()
    }
}