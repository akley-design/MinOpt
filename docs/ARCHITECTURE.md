# Architecture

Modular monolith. Four independent layers: AI client → MCP interface → application/execution → Docker infrastructure.

```
AI client (OpenCode / any MCP client)
        │  MCP stdio (or streamable-http, loopback only)
        ▼
src/minsync/server.py      MCP layer: 28 tools, arg validation, uniform {ok,error} results
        ▼
src/minsync/app.py         Application assembly (MinSyncApp)
 ├─ workspaces.py          workspace CRUD + safe file ops (security_paths.py guards every path)
 ├─ tasks.py               queue/states/semaphore(max concurrent)/per-workspace locks/SQLite results
 ├─ projects.py            install/build/test command detection per profile
 ├─ archives.py            safe ZIP create/extract + artifacts (SHA-256)
 └─ storage.py             SQLite (stdlib): workspaces/tasks/artifacts, crash recovery
        ▼
src/minsync/docker_backend.py   Execution backend interface (DockerBackend; replaceable)
        ▼  trusted `docker` CLI, controlled argv only — user code is the container command
Docker Engine (Docker Desktop / WSL2) → hardened one-shot containers, workspace bind-mounted at /workspace
```

Data: `%LOCALAPPDATA%\MinSync\` (`workspaces/ artifacts/ logs/ state/minsync.db`), override with `MINSYNC_DATA_DIR`.

## Command sequence

```
client ──run_command(ws, python, argv=[python3,main.py])──▶ server
server ──submit──▶ TaskManager (queued → semaphore → workspace lock → running)
TaskManager ──backend.run──▶ DockerBackend.build_run_argv (pure, unit-tested)
  docker run --rm --cap-drop ALL --read-only --network none --memory 512m ...
  --mount type=bind,src=<workspace>,dst=/workspace <profile image> python3 main.py
backend streams stdout/stderr (bounded buffer) ──▶ TaskManager persists
  succeeded|failed|timed_out|cancelled + exit_code + duration ──▶ client
```

Profiles are lazy: an image is `docker build`-ed from `docker/<profile>/Dockerfile` on first use only, then cached (one build lock per image). Nothing heavy is pre-pulled. Containers are one-shot, so dependency installs persist **in the workspace**: pip `--target .minsync_deps` (+PYTHONPATH), npm `node_modules`, Go/Rust/.NET caches under `.cache/`, Maven `-Dmaven.repo.local=.cache/m2`. These caches are excluded from project ZIPs.
Interrupted tasks are marked `failed/interrupted` on startup — never fake successes.
