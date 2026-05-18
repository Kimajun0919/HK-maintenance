param(
    [string]$Version = "dev",
    [string]$OutputDir = "dist",
    [switch]$SkipRedaction
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

if (-not $SkipRedaction) {
    $docsStage = Join-Path $stage "organized_maintenance_docs_simple"
    if (Test-Path $docsStage) {
        $sensitiveLinePattern = "(?i)(password|passwd|\bpw\b|\bid\b\s*[:=/]|\broot\b|vpn|otp|apikey|api[_-]?key|secret|token|postgresql://|mysql://|mongodb://|\uBE44\uBC00\uBC88\uD638|\uACC4\uC815|\uAD00\uB9AC\uC790|\uC778\uC99D|Koreanairnew|kcnd|home2402|koag2170|dental7788|welcome1|home12)"
        Get-ChildItem -Path $docsStage -Recurse -File -Include *.md,*.txt |
            ForEach-Object {
                $content = Get-Content -LiteralPath $_.FullName -Encoding UTF8
                $redacted = $content | ForEach-Object {
                    if ($_ -match $sensitiveLinePattern) {
                        "[REDACTED sensitive credential line]"
                    } else {
                        $_
                    }
                }
                Set-Content -LiteralPath $_.FullName -Value $redacted -Encoding UTF8
            }
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
