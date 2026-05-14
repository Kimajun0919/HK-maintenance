$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-llm.txt

$env:USE_LLM = "1"
$env:LOCAL_LLM_MODEL = if ($env:LOCAL_LLM_MODEL) { $env:LOCAL_LLM_MODEL } else { "Qwen/Qwen2.5-0.5B-Instruct" }
$env:DOCS_DIR = (Resolve-Path "..\organized_maintenance_docs_simple").Path

Write-Host "Starting HK Maintenance RAG Chatbot with local LLM"
Write-Host "DOCS_DIR=$env:DOCS_DIR"
Write-Host "LOCAL_LLM_MODEL=$env:LOCAL_LLM_MODEL"

.\.venv\Scripts\python.exe app.py
