$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonPath = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
$HelperPath = Join-Path $ProjectRoot "scripts\benchmark_answers.py"
$EnvPath = Join-Path $ProjectRoot "backend\.env"

if (-not (Test-Path $PythonPath)) {
    & (Join-Path $ProjectRoot "scripts\setup.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Setup failed with exit code $LASTEXITCODE."
    }
}

$GeminiConfigured = $false
if (Test-Path $EnvPath) {
    $GeminiConfigured = [bool](Select-String `
        -Path $EnvPath `
        -Pattern '^GEMINI_API_KEY=(?!replace_with_your_gemini_api_key\s*$)\S+' `
        -Quiet)
}
if (-not $GeminiConfigured) {
    & (Join-Path $ProjectRoot "scripts\configure-gemini.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Gemini configuration failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Mentara M4 answer-model benchmark" -ForegroundColor Cyan
Write-Host "This makes 8 non-sensitive stateless Gemini requests." -ForegroundColor Yellow
& $PythonPath $HelperPath
if ($LASTEXITCODE -ne 0) {
    throw "Answer benchmark failed with exit code $LASTEXITCODE."
}

Write-Host "Benchmark complete. No API key was printed or saved in the result." -ForegroundColor Green
