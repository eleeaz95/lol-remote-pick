<#
.SYNOPSIS
    LoL Remote Pick - Windows PowerShell Launcher
.DESCRIPTION
    One-click launcher for Windows that checks Python/uv, sets up virtualenv,
    installs requirements, and launches the server with automatic browser & QR code display.
#>

param (
    [switch]$Mock,
    [switch]$NoBrowser,
    [int]$Port = 8000,
    [string]$Host = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  LoL Remote Pick - Control League of Legends from your Phone" -ForegroundColor Yellow
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Check if uv is available
$uvCmd = Get-Command "uv" -ErrorAction SilentlyContinue
if ($uvCmd) {
    Write-Host "[INFO] Detected 'uv' environment manager. Launching..." -ForegroundColor Green
    $extraArgs = @("run", "run.py", "--port", $Port, "--host", $Host)
    if ($Mock) { $extraArgs += "--mock" }
    if (-not $NoBrowser) { $extraArgs += "--open" }
    & uv @extraArgs
    exit $LASTEXITCODE
}

# 2. Check Python
$pyCmd = $null
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    $pyCmd = "py"
} elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    $pyCmd = "python"
}

if (-not $pyCmd) {
    Write-Host "`n[ERROR] Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please download and install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Important: Check '[X] Add Python to PATH' during installation.`n" -ForegroundColor Yellow
    Read-Host "Press Enter to exit..."
    exit 1
}

# 3. Create .venv if needed
$venvActivate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    Write-Host "[INFO] Creating virtual environment (.venv)..." -ForegroundColor Cyan
    & $pyCmd -m venv .venv
}

# 4. Activate virtualenv
& $venvActivate

# 5. Install dependencies
Write-Host "[INFO] Checking Python dependencies..." -ForegroundColor Cyan
& python -m pip install -r requirements.txt --quiet

# 6. Launch Application
Write-Host "[INFO] Starting LoL Remote Pick..." -ForegroundColor Green
$appArgs = @("run.py", "--port", $Port, "--host", $Host)
if ($Mock) { $appArgs += "--mock" }
if (-not $NoBrowser) { $appArgs += "--open" }

& python @appArgs
