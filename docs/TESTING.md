# Testing

```powershell
.\scripts\test.ps1            # everything
.\scripts\test.ps1 -UnitOnly  # unit+security+e2e (no Docker needed)
```
Linux dev equivalent: `.venv/bin/python -m pytest tests -v`

| Layer | File | What it proves |
|---|---|---|
| unit | `tests/unit/test_core.py` | path validation, workspace CRUD/quota, task states+results re-fetch, archive roundtrip, Zip-Slip rejection, exact hardened `docker run` argv (one workspace mount, cap-drop ALL, network none, no privileged) |
| security | `tests/security/test_security.py` | no `shell=True`/`os.system`/PowerShell in production source; no dangerous params in MCP schemas; symlink-escape & archive-limit rejection |
| integration | `tests/integration/test_docker.py` | **real containers**: python stdout/stderr/exit 7, timeout, cancel, C++ compile+run, Node run, host marker invisible, no network in `disabled`. All **skip with reason** when Docker is absent — never fake-pass |
| e2e | `tests/e2e/test_mcp_stdio.py` | real MCP client ↔ stdio server: tool list (28), workspace→write→read→archive→artifact→persistence; without Docker, run_command must fail as structured `docker_unavailable` (proves no host fallback) |

Test-only `FakeBackend` (in `tests/conftest.py`) simulates task outcomes; it is never imported by production code, and its results are never presented as Docker evidence.

Current verified result in the build sandbox (Linux, no Docker): **30 passed, 4 skipped** (3 integration + 1 live-isolation — all requiring Docker). Extra suites: `test_backend_fake_docker.py` exercises the real DockerBackend (argv/streaming/truncation/timeout/cancel) against a fake `docker` CLI — process-management evidence only, not container evidence; `test_reliability.py` covers read-only doctor, storage recovery ownership, workspace serialization vs cross-workspace parallelism, corrupt-ZIP cleanup, active-task delete guard. PowerShell scripts were syntax-checked with the tree-sitter PowerShell grammar (all OK; not executed on Windows). On a Windows machine with Docker Desktop running, the integration suite is the acceptance gate.
