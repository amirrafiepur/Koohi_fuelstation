$ErrorActionPreference = "Stop"

Write-Host "=== 140 Jahan Pour Windows build ===" -ForegroundColor Cyan

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher (py.exe) was not found."
}

$python = "py -3.11"

Write-Host "Checking Python..."
& py -3.11 --version

Write-Host "Installing pinned dependencies..."
& py -3.11 -m pip install -r requirements.txt

Write-Host "Running Django checks..."
& py -3.11 manage.py check

Write-Host "Running test suite..."
& py -3.11 manage.py test

Write-Host "Cleaning previous PyInstaller output..."
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }

Write-Host "Building onedir executable..."
& py -3.11 -m PyInstaller --clean --noconfirm FuelStation.spec

Write-Host ""
Write-Host "Build complete: dist\FuelStation\" -ForegroundColor Green
Write-Host "Run dist\FuelStation\FuelStation.exe for the Windows smoke test."
