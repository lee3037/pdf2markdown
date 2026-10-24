param([string]$UvPath = "uv")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
# This creates only gateway/.venv; no pip install in the existing MinerU environment.
$previousProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) ".venv"
    & $UvPath sync --project . --python 3.12 --locked --no-dev
    if ($LASTEXITCODE -ne 0) { throw "Gateway dependency setup failed." }
} finally {
    if ($null -eq $previousProjectEnvironment) {
        Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    } else {
        $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
    }
}
if (-not (Test-Path ".env")) {
    & ".\.venv\Scripts\python.exe" -m pure_gateway.init_config
    if ($LASTEXITCODE -ne 0) { throw "Gateway local configuration creation failed." }
}
Write-Host "Gateway environment ready. Token stays in .env and is not printed."
Write-Host "Next: .\windows\check-upstream.ps1; then .\windows\start.ps1"
