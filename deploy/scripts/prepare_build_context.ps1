# Generate isolated Docker build directory (avoids using user home as context)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Dest = Join-Path $Root ".docker-build"

Write-Host "Preparing Docker build context: $Dest"

if (Test-Path $Dest) {
    Remove-Item $Dest -Recurse -Force
}
New-Item -ItemType Directory -Path $Dest | Out-Null

$files = @("Dockerfile", "requirements.txt", "config.json", "characters.json")
Get-ChildItem $Root -Filter "*.py" -File | ForEach-Object { $files += $_.Name }

foreach ($f in ($files | Select-Object -Unique)) {
    $src = Join-Path $Root $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $Dest $f)
    }
}

$dirs = @("app", "admin", "api", "database", "deploy", "memory", "scoring", "scripts", "characters", "performance", "safety", "emotion", "arc", "worlds")
foreach ($d in $dirs) {
    $src = Join-Path $Root $d
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $Dest $d) -Recurse
    }
}

$size = (Get-ChildItem $Dest -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Done. Context size: {0:N2} MB" -f ($size / 1MB))
