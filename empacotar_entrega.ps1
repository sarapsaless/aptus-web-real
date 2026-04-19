# Empacota para o cliente: pasta APTUS (onedir) ou APTUS.exe (onefile) + assets + LEIA-ME
# Executar na pasta do projeto após o build:  .\empacotar_entrega.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pastaEntrega = Join-Path $PSScriptRoot "dist\Entrega_APTUS"
$onedirRoot = Join-Path $PSScriptRoot "dist\APTUS"
$onedirExe = Join-Path $onedirRoot "APTUS.exe"
$onefileExe = Join-Path $PSScriptRoot "dist\APTUS.exe"
$assetsOrig = Join-Path $PSScriptRoot "assets"

$modo = $null
if (Test-Path $onedirExe) {
    $modo = "onedir"
}
elseif (Test-Path $onefileExe) {
    $modo = "onefile"
}

if (-not $modo) {
    Write-Host "ERRO: Nao encontrado dist\APTUS\APTUS.exe nem dist\APTUS.exe." -ForegroundColor Red
    Write-Host "Execute o build: python -m PyInstaller aptus_onedir.spec --noconfirm --clean" -ForegroundColor Yellow
    exit 1
}

if (Test-Path $pastaEntrega) {
    Remove-Item $pastaEntrega -Recurse -Force
}
New-Item -ItemType Directory -Path $pastaEntrega | Out-Null

if ($modo -eq "onedir") {
    $destPrograma = Join-Path $pastaEntrega "APTUS"
    Copy-Item -Path $onedirRoot -Destination $destPrograma -Recurse -Force
}
else {
    Copy-Item -Path $onefileExe -Destination (Join-Path $pastaEntrega "APTUS.exe") -Force
}

function Copiar-AssetsPara($destinoPastaAssets) {
    New-Item -ItemType Directory -Path $destinoPastaAssets -Force | Out-Null
    if (Test-Path $assetsOrig) {
        Copy-Item -Path (Join-Path $assetsOrig "*") -Destination $destinoPastaAssets -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# Raiz do ZIP: assets\ (compativel com ZIP antigo)
Copiar-AssetsPara (Join-Path $pastaEntrega "assets")
# Exe em subpasta APTUS\: o programa procura APTUS\assets\ — obrigatorio copiar para la tambem
if ($modo -eq "onedir") {
    Copiar-AssetsPara (Join-Path $pastaEntrega "APTUS\assets")
}

$txtWindows = @"
================================================================================
APTUS — Como enviar e como o cliente deve abrir (IMPORTANTE)
================================================================================

ENVIE O PACOTE COMPLETO EM ZIP (nao envie só um .exe solto pela pasta Downloads).

• Extraia TODO o ZIP para uma pasta (Ambiente de trabalho ou Documentos).
• Se existir a pasta APTUS com APTUS.exe e _internal:
  Abra APTUS\APTUS.exe e NAO apague nem renomeie a pasta _internal (é obrigatória).

Motivo: o modo "um ficheiro só" extrai para uma pasta temporária e muitos antivírus
bloqueiam — a versão em pasta (APTUS + _internal) funciona em mais computadores.

================================================================================
Se o Windows bloquear ou avisar (SmartScreen / Proteção)
================================================================================

1) Botão direito no APTUS.exe → Propriedades → separador "Geral"
   Se aparecer "Desbloquear", marque-a e clique em OK.

2) Se abrir uma janela azul "O Windows protegeu o PC":
   Clique em "Mais informações" e depois em "Executar mesmo assim".

3) O antivírus pode pedir confirmação na primeira execução — é normal em programas
   que não estão na Microsoft Store.

4) Para distribuir sem estes avisos é necessário um certificado de assinatura de código
   (empresa). O executável gerado aqui não está assinado.

================================================================================
Erro ao abrir: falta DLL (VCRUNTIME140.dll, api-ms-win-*.dll, etc.)
================================================================================

Instale o Visual C++ Redistributable para x64 (Microsoft):
   https://aka.ms/vs/17/release/vc_redist.x64.exe

================================================================================
Pasta "assets" e LOGO (documentos PDF)
================================================================================

Os documentos clínicos precisam da imagem da clínica (logo_aptus.png ou .jpg).

Com a pasta APTUS (onedir), coloque a logo em:

   pasta_entrega\APTUS\assets\logo_aptus.png

Também funciona no mesmo ZIP (pasta assets ao lado de APTUS):

   pasta_entrega\assets\logo_aptus.png

Recomendado: manter as duas pastas assets iguais após alterar a logo.

Estrutura exemplo:

   pasta_entrega\
      APTUS\
         APTUS.exe
         _internal\
         assets\
            logo_aptus.png
      assets\
         logo_aptus.png
      LEIA-ME_WINDOWS.txt

================================================================================
"@

Set-Content -Path (Join-Path $pastaEntrega "LEIA-ME_WINDOWS.txt") -Value $txtWindows -Encoding UTF8

Write-Host ""
Write-Host "Pacote pronto para o cliente:" -ForegroundColor Green
Write-Host "  $pastaEntrega" -ForegroundColor Cyan
Write-Host ""
if ($modo -eq "onedir") {
    Write-Host "Modo: pasta APTUS (onedir) - envie ZIP com APTUS + assets + LEIA-ME_WINDOWS.txt" -ForegroundColor Gray
}
else {
    Write-Host "Modo: APTUS.exe unico - considere aptus_onedir.spec para mais compatibilidade" -ForegroundColor Yellow
}
Write-Host "Comprima Entrega_APTUS completa em ZIP antes de enviar por email/WhatsApp." -ForegroundColor Gray
