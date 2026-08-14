# Start Enterprise UI (FastAPI + built React on http://localhost:8000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "Installing/updating editable package (pip install -e .) ..."
py -m pip install -e . -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install -e . failed. Fix the environment and retry."
    exit 1
}

Write-Host "Starting COBOL Enterprise API on http://127.0.0.1:8000 ..."
Write-Host "Use this script (py -m cobol_error_scanner.api.server), not an old cobol-dashboard-api.exe from site-packages."
Write-Host "Open that URL in your browser (Operational Docs requires this server, not file:// or Streamlit alone)."
Write-Host ""

if (-not (Test-Path "web\dist\index.html")) {
    Write-Host "web\dist not found. Build the UI first:"
    Write-Host "  cd web"
    Write-Host "  npm install"
    Write-Host "  npm run build"
    Write-Host ""
}

py -m cobol_error_scanner.api.server
