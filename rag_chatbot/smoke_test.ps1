$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$env:USE_LLM = "0"
$env:PYTHONIOENCODING = "utf-8"
$env:DOCS_DIR = (Resolve-Path "..\organized_maintenance_docs_simple").Path

python test_retrieval.py
