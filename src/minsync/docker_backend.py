"""Docker execution backend.

Trust boundary: this module runs the *trusted* `docker` CLI with strictly
controlled argv (no host shell, ever). User code only ever runs as the
command of `docker run` - it is never executed by a host shell/interpreter.

Hardening applied to every container (verified in tests/test docker args and
in tests/security):
  --cap-drop ALL, no-new-privileges, non-root uid, read-only rootfs,
  tmpfs /tmp, pids/cpu/memory limits, --network none by default,
  single bind mount: exactly the workspace dir -> /workspace.
No docker socket, no privileged, no host network, no client-supplied flags.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .errors import DockerUnavailable, ImageMissing, InvalidArgument
from .profiles import Profile

NETWORK_MODES = ("disabled", "approved")  # see config: no fake 'restricted'


@dataclass
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: int = 0
    timed_out: bool = False
    cancelled: bool = False


@dataclass
class _Running:
    container: str
    process: asyncio.subprocess.Process | None = None
    cancelled: bool = False


def find_docker_dir(explicit: str = "") -> Path | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    # repo layout: <root>/docker, package layout: <root>/src/minsync -> ../../docker
    here = Path(__file__).resolve()
    candidates += [here.parents[2] / "docker", here.parents[1] / "docker", Path.cwd() / "docker"]
    for c in candidates:
        if c.is_dir():
            return c
    return None


class DockerBackend:
    """Production backend speaking to Docker Engine via the docker CLI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._running: dict[str, _Running] = {}
        self._built: set[str] = set()

    # -- diagnostics -----------------------------------------------------
    def docker_path(self) -> str | None:
        return shutil.which("docker")

    async def _docker(self, argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
        exe = self.docker_path()
        if not exe:
            raise DockerUnavailable(
                "docker CLI not found on PATH. Install Docker Desktop for Windows "
                "(WSL2 backend) from https://www.docker.com/products/docker-desktop/ "
                "and re-run doctor.ps1")
        proc = await asyncio.create_subprocess_exec(
            exe, *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise DockerUnavailable(f"docker {' '.join(argv[:2])} timed out") from None
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def diagnostics(self) -> dict:
        exe = self.docker_path()
        if not exe:
            return {"available": False, "cli": None,
                    "error": "docker CLI not found on PATH (Docker Desktop not installed?)"}
        try:
            rc, out, err = await self._docker(["version", "--format", "{{.Server.Version}}"], 15)
            if rc != 0:
                return {"available": False, "cli": exe,
                        "error": f"Docker Engine not reachable: {err.strip()[:300]}"}
            _, os_out, _ = await self._docker(["info", "--format", "{{.OSType}}/{{.Architecture}}"], 15)
            return {"available": True, "cli": exe, "server_version": out.strip(),
                    "engine_os_arch": os_out.strip()}
        except DockerUnavailable as e:
            return {"available": False, "cli": exe, "error": e.message}

    async def require_available(self) -> None:
        d = await self.diagnostics()
        if not d["available"]:
            raise DockerUnavailable(d.get("error") or "Docker unavailable")

    # -- images ------------------------------------------------------------
    async def ensure_image(self, profile: Profile) -> None:
        if profile.image in self._built:
            return
        rc, _, _ = await self._docker(["image", "inspect", profile.image], 30)
        if rc == 0:
            self._built.add(profile.image)
            return
        docker_dir = find_docker_dir(self.settings.docker_dir)
        ctx = docker_dir / profile.dockerfile_dir if docker_dir else None
        if ctx and (ctx / "Dockerfile").exists():
            rc, out, err = await self._docker(
                ["build", "-t", profile.image, str(ctx)], timeout=1200)
            if rc != 0:
                raise ImageMissing(
                    f"failed to build image {profile.image}: {err.strip()[-500:]}")
            self._built.add(profile.image)
            return
        raise ImageMissing(
            f"image {profile.image} not present and no Dockerfile found for profile "
            f"{profile.name!r}. Build it with: docker build -t {profile.image} docker/{profile.dockerfile_dir}")

    # -- execution -----------------------------------------------------------
    def build_run_argv(self, *, profile: Profile, workspace_dir: Path, task_id: str,
                       command_argv: list[str], network: str) -> tuple[str, list[str]]:
        """Pure function (unit-tested): builds the exact docker argv."""
        if network not in NETWORK_MODES:
            raise InvalidArgument(
                f"network must be one of {NETWORK_MODES}; 'restricted' is not offered "
                "because no verified egress-filtering proxy ships with MinSync v1")
        s = self.settings
        container = f"minsync-{task_id}"
        argv = [
            "run", "--rm", "--name", container,
            "--label", f"minsync.task={task_id}",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "10001:10001",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--cpus", str(s.cpus),
            "--memory", f"{s.memory_mb}m",
            "--memory-swap", f"{s.memory_mb}m",
            "--pids-limit", str(s.pids_limit),
            "--network", "none" if network == "disabled" else "bridge",
            "--mount", f"type=bind,src={workspace_dir},dst=/workspace",
            "--workdir", "/workspace",
            "--env", "HOME=/tmp",
            profile.image,
            *command_argv,
        ]
        return container, argv

    async def run(self, *, profile: Profile, workspace_dir: Path, task_id: str,
                  command_argv: list[str], network: str, timeout_seconds: int) -> ExecResult:
        await self.require_available()
        await self.ensure_image(profile)
        container, argv = self.build_run_argv(
            profile=profile, workspace_dir=workspace_dir, task_id=task_id,
            command_argv=command_argv, network=network)
        exe = self.docker_path()
        assert exe  # guarded by require_available
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            exe, *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        handle = _Running(container=container, process=proc)
        self._running[task_id] = handle
        limit = self.settings.max_output_bytes

        async def drain(stream) -> tuple[bytes, bool, int]:
            kept = bytearray()
            total = 0
            while True:
                chunk = await stream.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                if len(kept) < limit:
                    kept += chunk[: limit - len(kept)]
            return bytes(kept), total > limit, total

        timed_out = False
        try:
            (out, out_trunc, _), (err, err_trunc, _) = await asyncio.wait_for(
                asyncio.gather(drain(proc.stdout), drain(proc.stderr)), timeout=timeout_seconds)
            await proc.wait()
        except asyncio.TimeoutError:
            timed_out = True
            await self._kill_container(container)
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
            out, err = b"", b""
            out_trunc = err_trunc = False
            # re-drain whatever was buffered is not reliable post-kill; report timeout
        finally:
            self._running.pop(task_id, None)
        duration = int((time.monotonic() - started) * 1000)
        return ExecResult(
            exit_code=(None if (timed_out or handle.cancelled) else proc.returncode),
            stdout=out.decode(errors="replace"), stderr=err.decode(errors="replace"),
            stdout_truncated=out_trunc, stderr_truncated=err_trunc,
            duration_ms=duration, timed_out=timed_out, cancelled=handle.cancelled)

    async def _kill_container(self, container: str) -> None:
        try:
            await self._docker(["kill", container], timeout=15)
        except Exception:
            pass  # container may already be gone (--rm)

    async def cancel(self, task_id: str) -> bool:
        handle = self._running.get(task_id)
        if not handle:
            return False
        handle.cancelled = True
        await self._kill_container(handle.container)
        return True


class UnavailableBackend:
    """Never executes anything. Exists so a host without Docker fails with a
    clear diagnostic instead of falling back to host execution (forbidden)."""

    async def diagnostics(self) -> dict:
        return {"available": False, "error": "execution backend not configured"}

    async def run(self, **kwargs) -> ExecResult:  # pragma: no cover
        raise DockerUnavailable("execution backend not configured")

    async def cancel(self, task_id: str) -> bool:  # pragma: no cover
        return False
