$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendPath = Join-Path $ProjectRoot "backend"
$PythonPath = Join-Path $BackendPath ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonPath)) {
    throw "Backend environment is missing. Run setup.bat from the project root first."
}

Set-Location $BackendPath
Write-Host "Starting Mentara AI backend at http://localhost:8000" -ForegroundColor Cyan
& $PythonPath -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

