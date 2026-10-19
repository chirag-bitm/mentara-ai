$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FrontendPath = Join-Path $ProjectRoot "frontend"

if (-not (Test-Path (Join-Path $FrontendPath "node_modules"))) {
    throw "Frontend packages are missing. Run setup.bat from the project root first."
}

Set-Location $FrontendPath
Write-Host "Starting Mentara AI frontend at http://localhost:3000" -ForegroundColor Cyan
& npm.cmd run dev

