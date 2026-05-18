param(
    [string]$Version = "dev",
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$dist = Join-Path $root $OutputDir
$stage = Join-Path $dist "HK-maintenance-local-$Version"
$zipPath = Join-Path $dist "HK-maintenance-local-$Version.zip"

New-Item -ItemType Directory -Force -Path $dist | Out-Null
if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$include = @(
    "backend",
    "frontend",
    "organized_maintenance_docs_simple",
    "README.md",
    ".env.example",
    "start-local.bat",
    "stop-local.bat",
    "start-local.command",
    "stop-local.command"
)

foreach ($item in $include) {
    $source = Join-Path $root $item
    if (Test-Path $source) {
        Copy-Item -LiteralPath $source -Destination $stage -Recurse -Force
    }
}

$removePatterns = @(
    "**\__pycache__",
    "**\.venv",
    "**\*.pyc",
    "**\*.pyo",
    "**\*.log"
)

foreach ($pattern in $removePatterns) {
    Get-ChildItem -Path $stage -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like (Join-Path $stage $pattern) } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -Force
Write-Host "Created $zipPath"
