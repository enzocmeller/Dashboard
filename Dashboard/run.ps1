# US Corn Dashboard - gather data and rebuild index.html
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Write-Host "[ERROR] Python was not found on PATH." -ForegroundColor Red
  Write-Host "Install Python 3.10+ from https://www.python.org/downloads/ (check 'Add to PATH')."
  Read-Host "Press Enter to exit"
  exit 1
}

Write-Host ("Using " + (python --version))
python src\update.py
if ($LASTEXITCODE -ne 0) {
  Write-Host "Update failed - see messages above." -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

Write-Host "Opening dashboard..."
Invoke-Item (Join-Path $PSScriptRoot "index.html")
