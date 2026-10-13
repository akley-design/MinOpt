# Start MinSync MCP server (stdio by default - the mode MCP clients launch).
param([ValidateSet("stdio","streamable-http")][string]$Transport = "stdio", [ValidateRange(1,65535)][int]$Port = 8765)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\minsync.exe")) { Write-Error "Not installed. Run scripts\install.ps1 first."; exit 1 }
Write-Host "Starting MinSync (transport=$Transport). MCP clients usually start this themselves; use this for manual checks. Ctrl+C to stop." -ForegroundColor Cyan
if ($Transport -eq "stdio") { & .\.venv\Scripts\minsync.exe serve }
else { & .\.venv\Scripts\minsync.exe serve --transport streamable-http --host 127.0.0.1 --port $Port }
