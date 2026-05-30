Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$logsDir = Join-Path $repoRoot "logs"

New-Item -ItemType Directory -Force $logsDir | Out-Null

function Get-PythonCommand {
    $explicitPython = $env:DEV_PYTHON_EXE
    if ($explicitPython -and (Test-Path $explicitPython)) {
        return @{ Command = $explicitPython; Args = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and $py.Source -notlike "*WindowsApps*") {
        return @{ Command = "py"; Args = @("-3") }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notlike "*WindowsApps*") {
        return @{ Command = "python"; Args = @() }
    }

    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3 -and $python3.Source -notlike "*WindowsApps*") {
        return @{ Command = "python3"; Args = @() }
    }

    $pythonCandidates = @(
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python312\python.exe"
    )
    foreach ($candidate in $pythonCandidates) {
        if (Test-Path $candidate) {
            return @{ Command = $candidate; Args = @() }
        }
    }

    throw "Python 3.11+ nao encontrado. Instale Python de verdade ou defina DEV_PYTHON_EXE com o caminho completo do python.exe."
}

function Get-NodeCommand {
    $explicitNode = $env:DEV_NODE_EXE
    if ($explicitNode -and (Test-Path $explicitNode)) {
        return @{ Node = $explicitNode; Npm = (Join-Path (Split-Path $explicitNode) "npm.cmd") }
    }

    $nodeCandidates = @(
        (Join-Path $env:LocalAppData "Programs\nodejs\node.exe"),
        (Join-Path $env:LocalAppData "Programs\nodejs\npm.cmd"),
        "C:\Program Files\nodejs\node.exe",
        "C:\Program Files (x86)\nodejs\node.exe",
        "C:\Program Files\nodejs\npm.cmd",
        "C:\Program Files (x86)\nodejs\npm.cmd"
    )
    foreach ($candidate in $nodeCandidates) {
        if (Test-Path $candidate) {
            if ($candidate.ToLower().EndsWith("npm.cmd")) {
                return @{ Node = (Join-Path (Split-Path $candidate) "node.exe"); Npm = $candidate }
            }
            return @{ Node = $candidate; Npm = (Join-Path (Split-Path $candidate) "npm.cmd") }
        }
    }

    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node -and $node.Source -notlike "*WindowsApps*") {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
        if ($npm) {
            return @{ Node = $node.Source; Npm = $npm.Source }
        }
    }

    throw "Node.js nao encontrado. Instale Node.js LTS ou defina DEV_NODE_EXE com o caminho completo do node.exe."
}

function Ensure-FileFromExample {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetPath,

        [Parameter(Mandatory = $true)]
        [string]$ExamplePath,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (Test-Path $TargetPath) {
        Write-Host "$Label ja existe em $TargetPath"
        return
    }

    if (-not (Test-Path $ExamplePath)) {
        throw "Template nao encontrado: $ExamplePath"
    }

    Copy-Item $ExamplePath $TargetPath
    Write-Host "$Label criado em $TargetPath"
}

Ensure-FileFromExample -TargetPath (Join-Path $backendDir ".env.local") -ExamplePath (Join-Path $backendDir ".env.example") -Label "backend/.env.local"
Ensure-FileFromExample -TargetPath (Join-Path $frontendDir ".env.local") -ExamplePath (Join-Path $frontendDir ".env.local.example") -Label "frontend/.env.local"

$pythonInfo = Get-PythonCommand
$nodeInfo = Get-NodeCommand
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $pythonInfo.Command @($pythonInfo.Args) -m venv ".venv"
    if (-not (Test-Path $venvPython)) {
        throw "Falha ao criar a virtualenv em .venv. Verifique se o Python selecionado em DEV_PYTHON_EXE ou PATH e valido."
    }
    Write-Host "Virtualenv criada em .venv"
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")

$nodeModulesDir = Join-Path $frontendDir "node_modules"
if (-not (Test-Path $nodeModulesDir)) {
    Push-Location $frontendDir
    try {
        & $nodeInfo.Npm install
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "frontend/node_modules ja existe"
}

Write-Host "Bootstrap concluido. Use Run All Dev (CRM & Backend) ou os scripts em scripts/."