# Gera dist\APTUS\ com PyInstaller (onedir — RECOMENDADO para o cliente)
# Opcional um .exe só: python -m PyInstaller aptus.spec --noconfirm
# Uso: PowerShell:  cd E:\ultraimport ; .\build_dist.ps1
# Requer: pip install pyinstaller customtkinter openpyxl psycopg2-binary

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Instalando PyInstaller (se necessario)..." -ForegroundColor Cyan
python -m pip install pyinstaller --quiet

Write-Host "Compilando APTUS onedir (pode levar alguns minutos)..." -ForegroundColor Cyan
python -m PyInstaller aptus_onedir.spec --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host "Falha no PyInstaller (codigo $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

$exeOnedir = Join-Path $PSScriptRoot "dist\APTUS\APTUS.exe"
if (Test-Path $exeOnedir) {
    Write-Host "OK (onedir): $exeOnedir" -ForegroundColor Green
} else {
    Write-Host "Aviso: dist\APTUS\APTUS.exe nao encontrado." -ForegroundColor Yellow
}

$p = Join-Path $PSScriptRoot "empacotar_entrega.ps1"
if (Test-Path $p) {
    Write-Host "Empacotando Entrega_APTUS (exe + assets + LEIA-ME)..." -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File $p
}
