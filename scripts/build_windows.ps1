param(
    [switch]$SmokeTest
)

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
    if ($SmokeTest) {
        $report = Join-Path ([System.IO.Path]::GetTempPath()) ("TradingTools-smoke-" + [guid]::NewGuid() + ".json")
        try {
            $executable = Join-Path $repositoryRoot 'dist\TradingTools.exe'
            $process = Start-Process -FilePath $executable -ArgumentList @('--smoke-test', "`"$report`"") -PassThru
            if (-not $process.WaitForExit(120000)) {
                Stop-Process -Id $process.Id
                throw "Windows executable smoke test timed out"
            }
            if (-not (Test-Path -LiteralPath $report)) {
                throw "Windows executable did not produce its smoke-test report"
            }
            $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
            if ($process.ExitCode -ne 0 -or $result.status -ne 'passed' -or -not $result.frozen) {
                throw "Windows executable smoke test failed: $($result | ConvertTo-Json -Compress)"
            }
            $result | ConvertTo-Json
        }
        finally {
            if (Test-Path -LiteralPath $report) {
                Remove-Item -LiteralPath $report
            }
        }
    }
}
finally {
    Pop-Location
}
