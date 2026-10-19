$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendPath = Join-Path $ProjectRoot "backend"
$FrontendPath = Join-Path $ProjectRoot "frontend"
$PythonPath = Join-Path $BackendPath ".venv\Scripts\python.exe"
$ConstraintsPath = Join-Path $BackendPath "constraints.txt"

Write-Host ""
Write-Host "Mentara AI - project setup" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.11 and retry."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js and retry."
}

if (-not (Test-Path $PythonPath)) {
    Write-Host "[1/5] Creating backend Python environment..." -ForegroundColor Yellow
    & py -3.11 -m venv (Join-Path $BackendPath ".venv")
} else {
    Write-Host "[1/5] Backend Python environment already exists." -ForegroundColor Green
}

Write-Host "[2/5] Installing backend packages..." -ForegroundColor Yellow
& $PythonPath -m pip install --upgrade pip
& $PythonPath -m pip install `
    -r (Join-Path $BackendPath "requirements-dev.txt") `
    -c $ConstraintsPath

Write-Host "[3/5] Installing frontend packages..." -ForegroundColor Yellow
Push-Location $FrontendPath
try {
    if (Test-Path (Join-Path $FrontendPath "package-lock.json")) {
        & npm.cmd ci
    } else {
        & npm.cmd install
    }
} finally {
    Pop-Location
}

Write-Host "[4/5] Preparing environment files and Git repository..." -ForegroundColor Yellow

if (-not (Test-Path (Join-Path $BackendPath ".env"))) {
    Copy-Item (Join-Path $BackendPath ".env.example") (Join-Path $BackendPath ".env")
    Write-Host "Created backend\.env for Gemini configuration." -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $FrontendPath ".env.local"))) {
    Copy-Item (Join-Path $FrontendPath ".env.local.example") (Join-Path $FrontendPath ".env.local")
}

if ((Get-Command git -ErrorAction SilentlyContinue) -and -not (Test-Path (Join-Path $ProjectRoot ".git"))) {
    Push-Location $ProjectRoot
    try {
        & git init
    } finally {
        Pop-Location
    }
}

Write-Host "[5/5] Setup complete." -ForegroundColor Green
Write-Host "Next: run .\configure-gemini.bat and enter your Gemini API key."
Write-Host ""
