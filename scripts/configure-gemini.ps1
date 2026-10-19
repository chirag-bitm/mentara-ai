$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendPath = Join-Path $ProjectRoot "backend"
$EnvPath = Join-Path $BackendPath ".env"
$ExamplePath = Join-Path $BackendPath ".env.example"

Write-Host ""
Write-Host "Mentara AI - Gemini configuration" -ForegroundColor Cyan

if (-not (Test-Path $EnvPath)) {
    Copy-Item $ExamplePath $EnvPath
}

$SecureKey = Read-Host "Paste your Gemini API key (it will stay hidden)" -AsSecureString
$KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
try {
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPointer)
}

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    throw "No Gemini API key was entered. Nothing was changed."
}

$ApiKey = $ApiKey.Trim()
if ($ApiKey.Length -lt 20 -or $ApiKey -match '[\x00-\x20\x7F]') {
    throw @"
The entered value is not a valid API-key shape, so backend\.env was not changed.
Some PowerShell hosts capture Ctrl+V as a control character in hidden input.
Copy the key again, then paste with a single right-click or Shift+Insert and press Enter.
"@
}

$Lines = [Collections.Generic.List[string]]::new()
foreach ($Line in [IO.File]::ReadAllLines($EnvPath)) {
    $Lines.Add($Line)
}

function Set-EnvironmentValue {
    param(
        [string]$Name,
        [string]$Value
    )

    $Replacement = "$Name=$Value"
    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        if ($Lines[$Index] -match "^$([Regex]::Escape($Name))=") {
            $Lines[$Index] = $Replacement
            return
        }
    }
    $Lines.Add($Replacement)
}

Set-EnvironmentValue -Name "STT_PROVIDER" -Value "gemini"
Set-EnvironmentValue -Name "GEMINI_API_KEY" -Value $ApiKey
Set-EnvironmentValue -Name "GEMINI_MODEL" -Value "gemini-3.5-transcribe-live"
Set-EnvironmentValue -Name "GEMINI_LANGUAGE_CODES" -Value ""
Set-EnvironmentValue -Name "GEMINI_TRANSCRIPTION_MODE" -Value "VERBATIM"

$Utf8WithoutBom = [Text.UTF8Encoding]::new($false)
$Content = ($Lines -join [Environment]::NewLine) + [Environment]::NewLine
[IO.File]::WriteAllText($EnvPath, $Content, $Utf8WithoutBom)

$ApiKey = $null
Write-Host "Gemini is configured in backend\.env." -ForegroundColor Green
Write-Host "The API key was not placed in frontend files." -ForegroundColor Green
Write-Host "Next: run .\start-backend.bat" -ForegroundColor Yellow
Write-Host ""
