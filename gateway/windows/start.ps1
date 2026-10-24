$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Get-NetTCPConnection -State Listen -LocalPort 19092 -ErrorAction SilentlyContinue) {
    throw "Port 19092 is occupied. Nothing was stopped or reconfigured."
}
& ".\.venv\Scripts\python.exe" -m pure_gateway.probe
if ($LASTEXITCODE -ne 0) { throw "Native API preflight failed; gateway not started." }
& ".\.venv\Scripts\python.exe" -m pure_gateway.serve
if ($LASTEXITCODE -ne 0) { throw "Gateway stopped with a nonzero exit code." }
