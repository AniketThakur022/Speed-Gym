# =================================================================
# OCR Stack Deploy Script (Windows PowerShell)
# =================================================================
# Run this in PowerShell to build and start the OCR Docker service.
# Prerequisites: Docker Desktop for Windows with WSL2 backend.
# =================================================================

param(
    [switch]$Build,
    [switch]$Up,
    [switch]$Down,
    [switch]$Test,
    [string]$Book = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$ComposeFile = "$ProjectRoot\docker-compose.ocr.yml"

Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "  Vedic Brain -- OCR Stack Deploy" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan

# -- Check Docker --
Write-Host "`n[1/5] Checking Docker Desktop..." -ForegroundColor Yellow
try {
    $dockerInfo = docker info 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Docker not responding" }
    Write-Host "  [OK] Docker is running" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Docker Desktop not running. Start Docker Desktop first." -ForegroundColor Red
    exit 1
}

# -- Build --
if ($Build -or $Up -or $Test) {
    Write-Host "`n[2/5] Building OCR service image..." -ForegroundColor Yellow
    docker compose -f $ComposeFile build ocr
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] Build failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Image built: webapp-brain-ocr" -ForegroundColor Green
}

# -- Start --
if ($Up -or $Test) {
    Write-Host "`n[3/5] Starting OCR service..." -ForegroundColor Yellow
    docker compose -f $ComposeFile up -d ocr
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] Failed to start service" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] OCR service started (container: brain_ocr)" -ForegroundColor Green

    # Wait a moment for health check
    Write-Host "`n[4/5] Waiting for health check..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
    $health = docker inspect --format='{{.State.Health.Status}}' brain_ocr 2>$null
    if ($health -eq "healthy" -or $health -eq "<no value>") {
        Write-Host "  [OK] Service is healthy" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] Health check pending ($health) -- continuing anyway" -ForegroundColor Yellow
    }
}

# -- Test --
if ($Test) {
    Write-Host "`n[5/5] Running OCR sanity test..." -ForegroundColor Yellow
    docker compose -f $ComposeFile exec -T ocr python -c "import fitz, pytesseract, cv2; from PIL import Image; print('PyMuPDF:', fitz.version); print('Tesseract:', pytesseract.get_tesseract_version()); print('OpenCV:', cv2.__version__); print('PIL:', Image.__version__); print('--- All OCR dependencies loaded successfully ---')"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] Test failed -- check logs:" -ForegroundColor Red
        docker compose -f $ComposeFile logs ocr --tail 20
        exit 1
    }
    Write-Host "  [OK] All OCR libraries verified inside container" -ForegroundColor Green
}

# -- Run Pipeline --
if ($Book) {
    Write-Host "`n[6/5] Running OCR pipeline for: $Book" -ForegroundColor Yellow
    docker compose -f $ComposeFile exec -T ocr python -X utf8 scripts/page_ocr_pipeline.py --book $Book --resume
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] Pipeline failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Pipeline completed for $Book" -ForegroundColor Green
}

# -- Down --
if ($Down) {
    Write-Host "`nStopping OCR service..." -ForegroundColor Yellow
    docker compose -f $ComposeFile down
    Write-Host "  [OK] Service stopped" -ForegroundColor Green
}

Write-Host "`n===========================================================" -ForegroundColor Cyan
Write-Host "  Done!" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan

if ($Up -or $Test) {
    Write-Host "`nNext steps:" -ForegroundColor White
    Write-Host "  1. Run OCR pipeline: .\deploy_ocr.ps1 -Book 'CAT_DI_LR_Nishit_K_Sinha'" -ForegroundColor Cyan
    Write-Host "  2. Open page_view.html in browser to review pages" -ForegroundColor Cyan
    Write-Host "  3. Use this container for any Python/OCR work:" -ForegroundColor Cyan
    Write-Host "     docker compose -f docker-compose.ocr.yml exec ocr bash" -ForegroundColor DarkCyan
}
