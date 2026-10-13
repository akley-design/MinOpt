# Run MinSync test suite. Docker integration tests skip (with reason) without Docker.
param([switch]$UnitOnly)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Error "Run scripts\install.ps1 first."; exit 1 }
if ($UnitOnly) { & .\.venv\Scripts\python.exe -m pytest tests/unit tests/security tests/e2e -v }
else { & .\.venv\Scripts\python.exe -m pytest tests -v }
exit $LASTEXITCODE
