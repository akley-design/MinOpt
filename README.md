# MinSync

Universal isolated command executor, MCP server and agent programming environment for **Windows 11**.

AI agents create persistent workspaces, write code, compile/run/test it in hardened Docker containers, and produce ZIP artifacts — **user code never executes on the host Windows system**. There is no host-shell fallback: without Docker, execution tools return a structured `docker_unavailable` error.

## Requirements

- Windows 11, Python 3.11+
- Docker Desktop with Linux containers (WSL2 backend) — installed by you; MinSync never installs it or changes Windows settings
- Any MCP client (OpenCode recommended; see `docs/MCP_SETUP.md`)

Linux/macOS also work for development (same code, `~/.local/share/minsync` data dir).

## Quick start (Windows PowerShell)

```powershell
git clone <this repo> MinSync; cd MinSync
.\scripts\install.ps1      # checks Python/Docker, creates .venv, installs pinned deps (mcp==1.30.0)
.\scripts\doctor.ps1       # diagnoses Docker Engine; exit 2 if not ready
.\scripts\start.ps1        # manual stdio run (MCP clients normally start it themselves)
.\scripts\test.ps1         # full test suite (Docker tests skip with reason if no Docker)
.\scripts\stop.ps1         # stops only MinSync processes/containers; never deletes projects
```

## First check (no ChatGPT needed)

1. Add MinSync to OpenCode using `examples/opencode.json` (fix the two paths).
2. Ask the agent: *"Use minsync: health_check, create a workspace, write `main.py` printing hello, run it with profile python, then create_archive."*
3. Or reproduce without any AI client:

```powershell
.\.venv\Scripts\minsync.exe doctor
.\.venv\Scripts\minsync.exe profiles
```

The automated end-to-end equivalent (real MCP stdio client ↔ server, workspace → file → archive) is `tests/e2e/test_mcp_stdio.py`; real container execution is `tests/integration/test_docker.py`.

## What it is / is not

- ✅ Docker-isolated argv/shell execution, profiles (python, cpp, node, go, rust, java, dotnet, bash), task queue with timeout/cancel/parallelism, safe ZIP, artifacts with SHA-256.
- ✅ Network off by default (`--network none`); `approved` = explicit unrestricted bridge for dependency installs.
- ❌ Not a Windows VM: CMD/.exe/.NET Framework are not supported (Linux containers).
- ❌ No verified `restricted` egress mode in v1 — rather than faking one, it is refused (see `docs/SECURITY.md`).
- ❌ ChatGPT Free cannot connect custom MCP servers (platform limit, see `docs/CHATGPT_INTEGRATION.md`). Use OpenCode locally.

Docs: `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/MCP_SETUP.md`, `docs/CHATGPT_INTEGRATION.md`, `docs/CONFIGURATION.md`, `docs/TROUBLESHOOTING.md`, `docs/TESTING.md`.
