# Stop ONLY MinSync processes. Never stops Docker Desktop or other containers.
# Running task containers are labelled minsync.task=* and are removed by name prefix.
$ErrorActionPreference = "Continue"
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "minsync" -and $_.CommandLine -match "serve" }
if (-not $procs) { Write-Host "No MinSync server process found." } 
foreach ($p in $procs) { Write-Host "Stopping MinSync PID $($p.ProcessId)"; Stop-Process -Id $p.ProcessId -ErrorAction SilentlyContinue }
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $names = docker ps --filter "label=minsync.task" --format "{{.Names}}"
    foreach ($n in $names) { if ($n) { Write-Host "Removing task container $n"; docker rm -f $n | Out-Null } }
}
Write-Host "Stopped. Workspaces/artifacts under %LOCALAPPDATA%\MinSync were NOT deleted." -ForegroundColor Green
