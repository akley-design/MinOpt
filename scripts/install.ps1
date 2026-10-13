# MinSync installer (Windows 11). Checks prerequisites, creates .venv, installs pinned deps.
# Does NOT install Docker Desktop, enable Windows features, or change ExecutionPolicy.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== MinSync install ==" -ForegroundColor Cyan
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python 3.11+ not found. Install from https://www.python.org/downloads/windows/ (check 'Add python.exe to PATH'), then re-run."
    exit 1
}
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Error "Python 3.11+ required."; exit 1 }

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed."; exit 1 }

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Warning "Docker CLI not found. Install Docker Desktop (WSL2 backend): https://www.docker.com/products/docker-desktop/ - MinSync will NOT install it for you."
} else {
    docker version | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Warning "Docker CLI present but Engine not reachable. Start Docker Desktop and re-run scripts\doctor.ps1" }
}
Write-Host "Install OK. Next: scripts\doctor.ps1, then scripts\start.ps1" -ForegroundColor Green
