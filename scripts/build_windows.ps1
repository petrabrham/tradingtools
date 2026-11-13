$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

Push-Location $repositoryRoot

try {
    & $python -m PyInstaller --noconfirm --clean packaging\TradingTools.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
