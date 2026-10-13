"""Task management: queue, states, bounded parallelism, per-workspace
serialization, cancellation, timeout, persisted results.

States: queued -> running -> succeeded | failed | timed_out | cancelled
(cancelling is transient while a cancel is in flight).

Cancellation contract: cancel() always drives the task to a terminal
state - queued runners are cancelled, running containers are killed via
the backend, and if the runner does not settle in time the record is
still closed as `cancelled` (the backend already killed the container).
A caller-side cancellation of a waiting submit likewise marks the task
cancelled instead of leaving it `running` forever.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time

from .config import Settings
from .errors import InvalidArgument, TaskNotFound
from .profiles import get_profile
from .storage import Storage
from .workspaces import WorkspaceManager

TERMINAL = {"succeeded", "failed", "timed_out", "cancelled"}


class TaskManager:
    def __init__(self, settings: Settings, storage: Storage, workspaces: WorkspaceManager, backend):
        self.settings = settings
        self.storage = storage
        self.workspaces = workspaces
        self.backend = backend
        self._sem = asyncio.Semaphore(settings.max_concurrent_tasks)
        self._ws_locks: dict[str, asyncio.Lock] = {}
        self._runners: dict[str, asyncio.Task] = {}
        # This component owns execution: recovering interrupted tasks and
        # pruning old ones happens here, not in read-only diagnostics.
        self.storage.recover_interrupted()
        self.storage.cleanup_old_tasks(settings.task_retention_days)

    # ------------------------------------------------------------------
    def _ws_lock(self, workspace_id: str) -> asyncio.Lock:
        return self._ws_locks.setdefault(workspace_id, asyncio.Lock())

    async def submit(
        self,
        *,
        workspace_id: str,
        profile_name: str,
        argv: list[str] | None,
        shell_script: str | None,
        kind: str = "run",
        network: str | None = None,
        timeout_seconds: int | None = None,
        wait: bool = True,
    ) -> dict:
        ws_root = self.workspaces.root(workspace_id)  # validates workspace exists
        profile = get_profile(profile_name)
        if bool(argv) == bool(shell_script):
            raise InvalidArgument("provide exactly one of argv / shell_script")
        if argv is not None:
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(a, str) and a and "\x00" not in a for a in argv)
            ):
                raise InvalidArgument("argv must be a non-empty list of non-empty strings")
            if len(argv) > 256 or any(len(a) > 8192 for a in argv):
                raise InvalidArgument("argv too large (max 256 args x 8192 chars)")
            command_argv = list(argv)
            command_desc: dict = {"argv": list(argv)}
        else:
            if not isinstance(shell_script, str) or not shell_script.strip():
                raise InvalidArgument("shell_script must be a non-empty string")
            if len(shell_script) > 65_536:
                raise InvalidArgument("shell_script too large (>64 KiB)")
            command_argv = ["sh", "-c", shell_script]
            command_desc = {"shell": shell_script}
        timeout = timeout_seconds or self.settings.task_timeout_seconds
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout < 1
            or timeout > self.settings.max_timeout_seconds
        ):
            raise InvalidArgument(f"timeout_seconds must be 1..{self.settings.max_timeout_seconds}")
        net = network or self.settings.default_network

        task_id = "task_" + secrets.token_hex(6)
        self.storage.add_task(
            {
                "id": task_id,
                "workspace_id": workspace_id,
                "profile": profile_name,
                "kind": kind,
                "command": command_desc,
                "status": "queued",
                "created_at": time.time(),
            }
        )
        runner = asyncio.create_task(
            self._execute(
                task_id=task_id,
                workspace_id=workspace_id,
                ws_root=ws_root,
                profile=profile,
                command_argv=command_argv,
                network=net,
                timeout=timeout,
            )
        )
        self._runners[task_id] = runner
        runner.add_done_callback(lambda _t, tid=task_id: self._runners.pop(tid, None))
        if wait:
            try:
                await runner
            except asyncio.CancelledError:
                # The MCP caller went away / was cancelled: don't leave the
                # task running invisibly - cancel it for real.
                runner.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(runner), timeout=15)
                except BaseException:
                    pass
                cur = self.storage.get_task(task_id)
                if cur and cur["status"] not in TERMINAL:
                    self.storage.update_task(task_id, status="cancelled", finished_at=time.time())
                raise
        return self.get(task_id)

    async def _execute(
        self, *, task_id, workspace_id, ws_root, profile, command_argv, network, timeout
    ) -> None:
        try:
            async with self._sem:  # global parallelism bound
                async with self._ws_lock(workspace_id):  # same workspace: serialized
                    cur = self.storage.get_task(task_id)
                    if cur and cur["status"] in TERMINAL:
                        return
                    self.storage.update_task(task_id, status="running", started_at=time.time())
                    try:
                        result = await self.backend.run(
                            profile=profile,
                            workspace_dir=ws_root,
                            task_id=task_id,
                            command_argv=command_argv,
                            network=network,
                            timeout_seconds=timeout,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # backend errors fail THIS task only
                        code = getattr(e, "code", "execution_error")
                        self.storage.update_task(
                            task_id,
                            status="failed",
                            finished_at=time.time(),
                            error_code=code,
                            error_message=str(e)[:2000],
                        )
                        return
                    if result.timed_out:
                        status = "timed_out"
                    elif result.cancelled:
                        status = "cancelled"
                    elif result.exit_code == 0:
                        status = "succeeded"
                    else:
                        status = "failed"
                    self.storage.update_task(
                        task_id,
                        status=status,
                        finished_at=time.time(),
                        exit_code=result.exit_code,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        stdout_truncated=int(result.stdout_truncated),
                        stderr_truncated=int(result.stderr_truncated),
                        duration_ms=result.duration_ms,
                        error_code=("timeout" if result.timed_out else None),
                        error_message=(f"exceeded {timeout}s" if result.timed_out else None),
                    )
        except asyncio.CancelledError:
            try:
                await self.backend.cancel(task_id)
            except BaseException:
                pass  # best effort while already being cancelled
            cur = self.storage.get_task(task_id)
            if cur and cur["status"] not in TERMINAL:
                self.storage.update_task(task_id, status="cancelled", finished_at=time.time())
            raise

    # ------------------------------------------------------------------
    def get(self, task_id: str, include_output: bool = True) -> dict:
        if not isinstance(task_id, str):
            raise TaskNotFound(f"unknown task: {task_id!r}")
        t = self.storage.get_task(task_id)
        if not t:
            raise TaskNotFound(f"unknown task: {task_id}")
        out = {
            k: t[k]
            for k in (
                "id",
                "workspace_id",
                "profile",
                "kind",
                "status",
                "created_at",
                "started_at",
                "finished_at",
                "exit_code",
                "duration_ms",
                "stdout_truncated",
                "stderr_truncated",
                "error_code",
                "error_message",
            )
        }
        out["command"] = _safe_json(t.get("command_json"))
        if include_output:
            out["stdout"] = t.get("stdout") or ""
            out["stderr"] = t.get("stderr") or ""
        return out

    def output(self, task_id: str, stream: str = "stdout", offset: int = 0, limit: int = 65_536) -> dict:
        t = self.get(task_id)
        if stream not in ("stdout", "stderr"):
            raise InvalidArgument("stream must be 'stdout' or 'stderr'")
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 262_144)
        text = t[stream]
        return {
            "task_id": task_id,
            "stream": stream,
            "offset": offset,
            "content": text[offset : offset + limit],
            "total_chars": len(text),
            "truncated": bool(t[f"{stream}_truncated"]),
        }

    async def cancel(self, task_id: str) -> dict:
        t = self.storage.get_task(task_id) if isinstance(task_id, str) else None
        if not t:
            raise TaskNotFound(f"unknown task: {task_id}")
        if t["status"] in TERMINAL:
            return self.get(task_id)
        self.storage.update_task(task_id, status="cancelling")
        runner = self._runners.get(task_id)
        killed = False
        try:
            killed = await self.backend.cancel(task_id)
        except Exception:
            killed = False
        if runner and not runner.done():
            if not killed:
                runner.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(runner), timeout=15)
            except Exception:
                pass
        cur = self.storage.get_task(task_id)
        if cur and cur["status"] not in TERMINAL:
            self.storage.update_task(task_id, status="cancelled", finished_at=time.time())
        return self.get(task_id)

    def list(self, workspace_id: str | None = None, limit: int = 50) -> list[dict]:
        limit = min(max(1, int(limit)), 200)
        return [self.get(t["id"], include_output=False) for t in self.storage.list_tasks(workspace_id, limit)]


def _safe_json(s):
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}
