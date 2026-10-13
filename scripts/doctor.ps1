# MinSync diagnostics: Python, Docker CLI/Engine, data dir. Exit 2 if Docker not ready.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "== MinSync doctor ==" -ForegroundColor Cyan
if (Get-Command python -ErrorAction SilentlyContinue) { python --version } else { Write-Warning "Python not found: https://www.python.org/downloads/windows/" }
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker --version
    docker version
    if ($LASTEXITCODE -ne 0) { Write-Warning "Docker Engine unreachable. Start Docker Desktop (WSL2 backend): https://www.docker.com/products/docker-desktop/" }
} else { Write-Warning "docker CLI not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop/" }
if (Test-Path ".venv\Scripts\minsync.exe") { & .\.venv\Scripts\minsync.exe doctor; exit $LASTEXITCODE }
Write-Warning "MinSync not installed yet: run scripts\install.ps1"
exit 1
