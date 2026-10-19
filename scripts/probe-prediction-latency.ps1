$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonPath = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
$EnvPath = Join-Path $ProjectRoot "backend\.env"

if (-not (Test-Path $PythonPath)) {
    throw "Backend environment is missing. Run setup.bat from the project root first."
}
if (-not (Test-Path $EnvPath)) {
    throw "Gemini is not configured. Run configure-gemini.bat privately first."
}

Write-Host "Mentara M5.5 bounded latency probe" -ForegroundColor Cyan
Write-Host "At most two non-sensitive stateless Gemini requests; no backend/frontend restart." -ForegroundColor Yellow
& $PythonPath (Join-Path $ProjectRoot "scripts\probe_prediction_latency.py")
if ($LASTEXITCODE -ne 0) {
    throw "Latency probe failed with exit code $LASTEXITCODE. Inspect docs\MILESTONE_5_5_LATENCY_PROBE.json."
}
Write-Host "Probe finished. Only sanitized timing and token usage were saved." -ForegroundColor Green
