# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker_unavailable: docker CLI not found` | Docker Desktop not installed. Install (WSL2 backend) from docker.com, start it, run `docker version` in PowerShell, re-run `scripts\doctor.ps1`. MinSync intentionally has no host-execution fallback. |
| CLI found, Engine unreachable | Docker Desktop not started / wrong context (`docker context use desktop-linux`). |
| `image_missing` | First run builds `minsync/<profile>` from `docker\<profile>\Dockerfile` automatically; if the Dockerfile isn't found (unusual install layout), build manually: `docker build -t minsync/python:3.12 docker\python`, or set `MINSYNC_DOCKER_DIR`. |
| Task `timed_out` | Increase `timeout_seconds` (≤900) or `MINSYNC_MAX_TIMEOUT_SECONDS`. Container was killed; partial output may be empty. |
| `path_traversal` | Use workspace-relative paths (`src/main.py`), never `C:\...`, `../`, or absolute paths. Workspaces are addressed by ID, not Windows paths. |
| `quota_exceeded` | File/archive/workspace limit hit — see `docs/CONFIGURATION.md`, split uploads, raise the specific limit deliberately. |
| OpenCode doesn't list tools | Check paths in `opencode.json` point to `.venv\Scripts\minsync.exe`, restart OpenCode, verify standalone: `minsync.exe doctor`; run `pytest tests/e2e` to prove the server itself. |
| HTTP transport won't bind LAN IP | By design (no built-in auth in v1). Bind 127.0.0.1; use Secure MCP Tunnel / a secured reverse proxy externally. |
| .NET/CMD/.exe won't run | Linux containers only — not a Windows VM. Use Linux-compatible builds; Windows-specific execution is out of scope. |
| PowerShell script blocked | Run from an already-allowed context, e.g. `powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1` for that one invocation. MinSync never changes global ExecutionPolicy. |
