# ============================================================
# Harness ?? - Docker Desktop ??????
# ??:???????? PowerShell,??:
#   cd C:\Users\guang
#   .\install_docker.ps1
# ============================================================

$ErrorActionPreference = "Stop"

Write-Host "`n=== Harness ?? Docker Desktop ???? ===`n" -ForegroundColor Cyan

# --- Step 1: ?? WSL2 ?? ---
Write-Host "[1/6] ?? WSL2 / Ubuntu ??..." -ForegroundColor Yellow
try {
    $wslOutput = wsl -l -v 2>$null
    Write-Host $wslOutput
    if ($wslOutput -notmatch "Ubuntu.*Running") {
        Write-Host "? Ubuntu ???,????..." -ForegroundColor Yellow
        wsl -d Ubuntu echo ok | Out-Null
    }
    Write-Host "? WSL2 ????`n" -ForegroundColor Green
}
catch {
    Write-Host "? WSL2 ???,?????? Ubuntu ?????`n" -ForegroundColor Red
    exit 1
}

# --- Step 2: ?????? Docker ---
Write-Host "[2/6] ?? Docker ?????..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version 2>$null
    Write-Host "? Docker ???:$dockerVersion" -ForegroundColor Green
    Write-Host "   ??????,??????...`n" -ForegroundColor Gray
    $skipInstall = $true
}
catch {
    Write-Host "? Docker ???,????...`n" -ForegroundColor Gray
    $skipInstall = $false
}

# --- Step 3: ?? Docker Desktop(winget ??,???????)---
if (-not $skipInstall) {
    Write-Host "[3/6] ??? winget ?? Docker Desktop..." -ForegroundColor Yellow
    # ?? winget ????
    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Host "   ??? winget,????(? 500MB,????)...`n" -ForegroundColor Gray
        winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) {
            Write-Host "? Docker Desktop ????`n" -ForegroundColor Green
        }
        else {
            Write-Host "? winget ????,?????:https://www.docker.com/products/docker-desktop/`n" -ForegroundColor Red
            exit 1
        }
    }
    else {
        Write-Host "? ???? winget,???????:" -ForegroundColor Red
        Write-Host "   https://www.docker.com/products/docker-desktop/`n" -ForegroundColor Yellow
        Write-Host "   ???????,?? 'Use WSL 2 instead of Hyper-V'`n" -ForegroundColor Gray
        exit 1
    }

    Write-Host "[!] ????,Docker Desktop ?????????,???????" -ForegroundColor Yellow
    Write-Host "   ????????? Docker ???????`n" -ForegroundColor Gray
    Read-Host "??????????..."
}

# --- Step 4: ?? Docker ?? ---
Write-Host "[4/6] ?? Docker ????..." -ForegroundColor Yellow
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden -ErrorAction SilentlyContinue
Start-Sleep 8

$retry = 0
do {
    try {
        $info = docker info 2>$null
        Write-Host "? Docker ???`n" -ForegroundColor Green
        break
    }
    catch {
        $retry++
        Write-Host "   ?? Docker ??... ($retry/6)" -ForegroundColor Gray
        Start-Sleep 5
    }
} while ($retry -lt 6)

docker --version
docker compose version
Write-Host ""

# --- Step 5: ?? File Sharing ---
Write-Host "[5/6] ?? Docker File Sharing..." -ForegroundColor Yellow
$wslMount = wsl -- docker run --rm -v C:\Users\guang:/mnt/test alpine ls /mnt/test 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "? C:\Users\guang ???????`n" -ForegroundColor Green
}
else {
    Write-Host "? ???????,???? Docker Desktop:" -ForegroundColor Yellow
    Write-Host "   Settings ? Resources ? File Sharing ? ?? C:\Users\guang ? Apply & Restart`n" -ForegroundColor Gray
}

# --- Step 6: ?? Harness ?? ---
Write-Host "[6/6] ?? Harness ????..." -ForegroundColor Yellow
Set-Location C:\Users\guang

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item .env.example .env
        Write-Host "? ??? .env.example ? .env" -ForegroundColor Yellow
        Write-Host "   ??? .env,?? SECRET_KEY ? ADMIN_PASSWORD ????`n" -ForegroundColor Gray
    }
    else {
        Write-Host "? ??? .env.example,?????????`n" -ForegroundColor Red
    }
}
else {
    Write-Host "? .env ???`n" -ForegroundColor Green
}

Write-Host "=== ???? ===" -ForegroundColor Cyan
Write-Host "???:"
Write-Host "  1. ?? C:\Users\guang\.env(SECRET_KEY?ADMIN_PASSWORD)"
Write-Host "  2. cd C:\Users\guang"
Write-Host "  3. docker compose up -d --build"
Write-Host "  4. curl http://localhost/health`n"
