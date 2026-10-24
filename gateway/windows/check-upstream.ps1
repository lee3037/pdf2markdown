$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
& ".\.venv\Scripts\python.exe" -m pure_gateway.probe --save-schema ".local\upstream-openapi.json"
if ($LASTEXITCODE -ne 0) { throw "Native API preflight failed. No PDF was uploaded; existing services were not changed." }
