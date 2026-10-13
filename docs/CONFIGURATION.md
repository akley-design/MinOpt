# Configuration

Environment variables only (see `.env.example`); defaults are conservative for a home PC.

| Var | Default | Meaning |
|---|---|---|
| `MINSYNC_DATA_DIR` | `%LOCALAPPDATA%\MinSync` | workspaces/artifacts/logs/state(SQLite) |
| `MINSYNC_MAX_CONCURRENT_TASKS` | 2 | parallel task cap (same workspace always serialized) |
| `MINSYNC_TASK_TIMEOUT_SECONDS` / `MINSYNC_MAX_TIMEOUT_SECONDS` | 120 / 900 | per-task default / ceiling |
| `MINSYNC_MEMORY_MB` / `MINSYNC_CPUS` / `MINSYNC_PIDS_LIMIT` | 512 / 1.0 / 128 | per-container limits (swap = RAM, so no swap growth) |
| `MINSYNC_MAX_OUTPUT_BYTES` | 262144 | kept stdout/stderr per stream (`truncated` flags overflow) |
| `MINSYNC_MAX_FILE_BYTES` / `MINSYNC_MAX_WORKSPACE_BYTES` | 5 MiB / 200 MiB | file/workspace quotas |
| `MINSYNC_MAX_ARCHIVE_BYTES` / `MINSYNC_MAX_UNCOMPRESSED_BYTES` / `MINSYNC_MAX_ARTIFACT_BYTES` | 20 / 100 / 50 MiB | ZIP & artifact limits |
| `MINSYNC_TASK_RETENTION_DAYS` | 7 | old finished tasks pruned at startup |
| `MINSYNC_DEFAULT_NETWORK` | `disabled` | `disabled` or `approved` |
| `MINSYNC_DOCKER_DIR` | auto-detected | folder containing per-profile Dockerfile dirs |
| `MINSYNC_CONTAINER_USER` | host uid:gid on POSIX (never 0), `10001:10001` on Windows | numeric `uid:gid` containers run as |

No dynamic "auto RAM detection" is claimed — limits are fixed and explicit. Secrets: MinSync needs none; containers receive no host env/secrets.
