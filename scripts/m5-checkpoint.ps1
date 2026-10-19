$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendPython = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
$FrontendModules = Join-Path $ProjectRoot "frontend\node_modules"
$BackendEnv = Join-Path $ProjectRoot "backend\.env"

Set-Location $ProjectRoot

if (-not (Test-Path $BackendPython) -or -not (Test-Path $FrontendModules)) {
    Write-Host "Dependencies are missing; running setup.bat..." -ForegroundColor Cyan
    & cmd.exe /d /c (Join-Path $ProjectRoot "setup.bat")
    if ($LASTEXITCODE -ne 0) {
        throw "setup.bat failed with exit code $LASTEXITCODE."
    }
}

$NeedsGeminiConfiguration = -not (Test-Path $BackendEnv)
if (-not $NeedsGeminiConfiguration) {
    $ConfiguredKeyLine = Get-Content $BackendEnv | Where-Object {
        $_ -match '^GEMINI_API_KEY=(.+)$' -and
        $_ -notmatch '^GEMINI_API_KEY=replace_with_your_gemini_api_key$'
    } | Select-Object -First 1
    $NeedsGeminiConfiguration = $null -eq $ConfiguredKeyLine
}

if ($NeedsGeminiConfiguration) {
    Write-Host "Gemini is not configured. The next prompt keeps your key hidden." -ForegroundColor Yellow
    & cmd.exe /d /c (Join-Path $ProjectRoot "configure-gemini.bat")
    if ($LASTEXITCODE -ne 0) {
        throw "Gemini configuration failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Running the complete automated gate through verify.bat..." -ForegroundColor Cyan
& cmd.exe /d /c (Join-Path $ProjectRoot "verify.bat")
if ($LASTEXITCODE -ne 0) {
    throw "verify.bat failed with exit code $LASTEXITCODE."
}

Write-Host "Starting backend and frontend in separate windows..." -ForegroundColor Cyan
Start-Process -FilePath (Join-Path $ProjectRoot "start-backend.bat") -WorkingDirectory $ProjectRoot
Start-Process -FilePath (Join-Path $ProjectRoot "start-frontend.bat") -WorkingDirectory $ProjectRoot

Write-Host ""
Write-Host "Automated checks passed and both servers were launched." -ForegroundColor Green
Write-Host "Keep both server windows open, then use Chrome at http://localhost:3000." -ForegroundColor Yellow
Write-Host "When the page is ready, perform the short M5 checklist supplied with this checkpoint." -ForegroundColor Yellow
