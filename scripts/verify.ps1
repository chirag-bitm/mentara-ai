$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendPath = Join-Path $ProjectRoot "backend"
$FrontendPath = Join-Path $ProjectRoot "frontend"
$PythonPath = Join-Path $BackendPath ".venv\Scripts\python.exe"

Write-Host "Running backend tests..." -ForegroundColor Cyan
Push-Location $BackendPath
try {
    & $PythonPath -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "Backend tests failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

Push-Location $FrontendPath
try {
    Write-Host "Running frontend reducer tests..." -ForegroundColor Cyan
    & npm.cmd run test
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend reducer tests failed with exit code $LASTEXITCODE."
    }

    Write-Host "Running frontend lint..." -ForegroundColor Cyan
    & npm.cmd run lint
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend lint failed with exit code $LASTEXITCODE."
    }

    Write-Host "Running frontend TypeScript check..." -ForegroundColor Cyan
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend TypeScript check failed with exit code $LASTEXITCODE."
    }

    Write-Host "Running frontend production build..." -ForegroundColor Cyan
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend production build failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

Write-Host "All automated checks passed." -ForegroundColor Green
