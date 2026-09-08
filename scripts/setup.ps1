$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Setup command failed (exit $LASTEXITCODE)." } }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 or newer from https://nodejs.org, then run START_SOLARFIT.bat again.' }
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .venv
        if ($LASTEXITCODE -ne 0) { & py -3.12 -m venv .venv }
        Check-Exit
    } else { throw 'Install Python 3.11 or 3.12 with the Python launcher from https://python.org.' }
}
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (-not (Test-Path '.venv/solarfit-ready')) {
    & $python -m pip install --upgrade pip
    Check-Exit
    & $python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
    Check-Exit
    New-Item '.venv/solarfit-ready' -ItemType File -Force | Out-Null
}
& $python -m pip install -r requirements.txt
Check-Exit
Push-Location frontend
try {
    & npm.cmd ci
    Check-Exit
    & npm.cmd run build
    Check-Exit
} finally { Pop-Location }
New-Item '.venv/solarfit-map-ready' -ItemType File -Force | Out-Null
Write-Host 'SolarFit setup complete.' -ForegroundColor Green
