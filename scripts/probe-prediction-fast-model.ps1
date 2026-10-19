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

Write-Host "Mentara M5.5 one-call fast-model comparison" -ForegroundColor Cyan
Write-Host "At most one non-sensitive stateless Gemini request; no servers needed." -ForegroundColor Yellow
& $PythonPath (Join-Path $ProjectRoot "scripts\probe_prediction_fast_model.py")
if ($LASTEXITCODE -ne 0) {
    throw "Fast-model probe failed with exit code $LASTEXITCODE. Inspect docs\MILESTONE_5_5_FAST_MODEL_PROBE.json."
}
Write-Host "Probe finished. Only sanitized timing, topic check and usage were saved." -ForegroundColor Green
