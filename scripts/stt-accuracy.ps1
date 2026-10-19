$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonPath = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
$HelperPath = Join-Path $ProjectRoot "scripts\stt_accuracy_profile.py"

if (-not (Test-Path $PythonPath)) {
    throw "Backend environment is missing. Run setup.bat first."
}

if ($args.Count -ne 1) {
    throw "Usage: .\stt-accuracy.bat begin|A|B|C|status|finish"
}

& $PythonPath $HelperPath $args[0]
if ($LASTEXITCODE -ne 0) {
    throw "STT accuracy profile command failed with exit code $LASTEXITCODE."
}
