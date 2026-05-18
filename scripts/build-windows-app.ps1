param(
    [string]$Version = "dev",
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$project = Join-Path $root "apps\windows\HKMaintenanceWindowsApp\HKMaintenanceWindowsApp.csproj"
$publishDir = Join-Path $root "$OutputDir\windows-app"
$zipPath = Join-Path $root "$OutputDir\HKMaintenance-Windows-$Version.zip"

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw "dotnet SDK is required. Install .NET 8 SDK."
}

New-Item -ItemType Directory -Force -Path (Join-Path $root $OutputDir) | Out-Null
if (Test-Path $publishDir) { Remove-Item -LiteralPath $publishDir -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

dotnet publish $project -c Release -r win-x64 --self-contained false -o $publishDir
Compress-Archive -Path (Join-Path $publishDir "*") -DestinationPath $zipPath -Force
Write-Host "Created $zipPath"
