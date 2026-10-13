# MCP setup

## OpenCode (verified format, opencode.ai/docs/mcp-servers)
Add to `opencode.json` (project) or `%USERPROFILE%\.config\opencode\opencode.json` (global) — merge the `mcp` key, do not overwrite other settings. Ready file: `examples/opencode.json`.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "minsync": {
      "type": "local",
      "command": ["C:\\Path\\To\\MinSync\\.venv\\Scripts\\minsync.exe", "serve"],
      "cwd": "C:\\Path\\To\\MinSync",
      "enabled": true,
      "environment": { "MINSYNC_DATA_DIR": "C:\\Users\\YOURNAME\\AppData\\Local\\MinSync" }
    }
  }
}
```

Notes: `command` is an array (executable + args); key is `environment` (not `env`); OpenCode v2 instead nests servers under `"mcp": {"servers": {...}}` with `disabled` instead of `enabled` — adapt if you run v2. Restart OpenCode, then ask it to call `health_check`.

Verify without OpenCode (reproducible): `pytest tests/e2e/test_mcp_stdio.py` spawns the real server over stdio with an MCP client, lists all 28 tools and runs workspace→file→archive.
Any stdio MCP client works the same way: command = `minsync.exe serve`.

## Streamable HTTP (optional, local only)
```powershell
.\.venv\Scripts\minsync.exe serve --transport streamable-http --host 127.0.0.1 --port 8765
```
Loopback only; the CLI refuses other binds (v1 has no built-in auth — do not port-forward it). Point a client at `http://127.0.0.1:8765/mcp`.

## Tools (28)
Info: `minsync_info environment_info list_profiles health_check` ·
Workspaces: `create_workspace list_workspaces inspect_workspace list_files read_file write_file edit_file delete_file search_files delete_workspace` ·
Execution: `run_command run_parallel get_task_status get_task_output cancel_task list_tasks` ·
Projects: `install_dependencies build_project run_tests upload_archive extract_archive create_archive list_artifacts get_artifact`.
All return `{"ok": bool, ...}` / `{"ok": false, "error": {"code","message"}}`.
