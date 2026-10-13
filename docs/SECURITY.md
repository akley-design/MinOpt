# Security

## Threat model
The MCP client/LLM is semi-trusted: it may generate arbitrary code. That code must never run on the host, escape its workspace, reach Docker Engine, or read user files. The MinSync process itself can control Docker — treat its host account as privileged; do not run it as Administrator unnecessarily, keep deps pinned (`requirements.lock.txt`), and never expose the HTTP transport beyond loopback in v1 (no built-in auth — the CLI refuses non-loopback binds).

## Enforced controls (implemented, and covered by tests)
- User code executes only as the command of `docker run` (argv list, no host shell). Verified: `tests/security` greps production source for `shell=True`/`os.system`/PowerShell and asserts hardening flags in the exact argv built by `DockerBackend.build_run_argv`.
- Every container: `--cap-drop ALL`, `no-new-privileges`, non-root uid (`MINSYNC_CONTAINER_USER`; host uid:gid on POSIX, never root, `10001:10001` on Windows), `--read-only` rootfs + tmpfs `/tmp`, `--memory/--memory-swap` (512 MB default), `--cpus`, `--pids-limit`, `--network none` by default, one bind mount (the workspace only → `/workspace`). No Docker socket, no privileged, no host network, no client-supplied image/mount/flags (tool schemas contain none).
- Paths: workspace-relative only; absolute/drive/`..`/NUL/symlink escapes rejected (`security_paths.resolve_within`); symlink entries refused in ZIPs; write-through-symlink refused.
- ZIP: limits on compressed/uncompressed size, file count, depth, compression ratio (bomb guards).
- Output: bounded buffers (default 256 KiB/stream, `truncated` flag), task timeout kills the container, cancellation kills by container name.
- Secrets: none are passed to containers; none logged; `.env` git-ignored.

## Network modes — honest naming
- `disabled` (default): `--network none`.
- `approved`: plain Docker bridge, **unrestricted egress** — explicit per-call opt-in (dependency installs default to it). Containers can then reach LAN/cloud-metadata addresses; use only when needed.
- `restricted`: **not offered**. No verified domain-filtering egress proxy ships in v1, so MinSync refuses the name rather than pretending bridge networking is restricted.

## Residual risks (not eliminated)
Docker is not a VM boundary: kernel exploits, Docker Desktop/WSL2 vulnerabilities, side channels, and resource exhaustion within limits remain possible. The host account running MinSync can administer Docker. `approved` networking is unrestricted. Keep Docker Desktop updated; run untrusted code with `disabled` networking.
