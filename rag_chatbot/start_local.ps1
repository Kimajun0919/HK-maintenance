$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:USE_LLM = "0"
$env:DOCS_DIR = (Resolve-Path "..\organized_maintenance_docs_simple").Path

Write-Host "Starting HK Maintenance RAG Chatbot"
Write-Host "DOCS_DIR=$env:DOCS_DIR"
Write-Host "USE_LLM=$env:USE_LLM"

.\.venv\Scripts\python.exe app.py
