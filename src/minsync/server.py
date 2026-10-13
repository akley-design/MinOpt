"""MCP layer: tool registration, argument validation, uniform errors.
All tools return JSON-serialisable dicts: {"ok": true, ...} or
{"ok": false, "error": {"code", "message", "details"}}.
Nothing except MCP protocol frames is written to stdout (stdio transport).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import functools
import logging
import sys

from mcp.server.fastmcp import FastMCP

from . import profiles as profiles_mod
from .app import VERSION, MinSyncApp
from .errors import InvalidArgument, MinSyncError
from .projects import build_command, install_command, test_command

log = logging.getLogger("minsync")


def _wrap(fn):
    @functools.wraps(fn)
    async def inner(*args, **kwargs):
        try:
            result = await fn(*args, **kwargs)
            return {"ok": True, **(result if isinstance(result, dict) else {"result": result})}
        except MinSyncError as e:
            return {"ok": False, "error": e.to_dict()}
        except Exception as e:  # last-resort: never crash the MCP session
            log.exception("tool failure")
            return {"ok": False, "error": {"code": "internal_error",
                                           "message": f"{type(e).__name__}: {e}", "details": {}}}
    return inner


def create_server(app: MinSyncApp | None = None, *, host: str = "127.0.0.1",
                  port: int = 8765) -> FastMCP:
    app = app or MinSyncApp()
    mcp = FastMCP("minsync", host=host, port=port)

    # ---------- info ----------
    @mcp.tool()
    @_wrap
    async def minsync_info() -> dict:
        """MinSync service/version/settings overview."""
        return {"service": "minsync", "version": VERSION, "settings": app.settings.public_dict(),
                "transports": ["stdio", "streamable-http (loopback only)"]}

    @mcp.tool()
    @_wrap
    async def environment_info() -> dict:
        """Host/runtime info and Docker diagnostics (no secrets)."""
        return await app.health()

    @mcp.tool()
    @_wrap
    async def health_check() -> dict:
        """Health + Docker availability. execution_ready=false means commands
        return docker_unavailable (there is no host-shell fallback)."""
        return await app.health()

    @mcp.tool()
    @_wrap
    async def list_profiles() -> dict:
        """Available language profiles (internally fixed images/tools)."""
        return {"profiles": profiles_mod.list_profiles()}

    # ---------- workspaces ----------
    @mcp.tool()
    @_wrap
    async def create_workspace(name: str = "workspace", profile: str = "") -> dict:
        """Create a persistent isolated workspace. Address it by returned id."""
        if profile:
            profiles_mod.get_profile(profile)
        return app.workspaces.create(name, profile or None)

    @mcp.tool()
    @_wrap
    async def list_workspaces() -> dict:
        return {"workspaces": app.workspaces.list()}

    @mcp.tool()
    @_wrap
    async def inspect_workspace(workspace_id: str) -> dict:
        return app.workspaces.inspect(workspace_id)

    @mcp.tool()
    @_wrap
    async def delete_workspace(workspace_id: str, confirm: bool = False) -> dict:
        """Permanently delete a workspace. Requires confirm=true."""
        return app.workspaces.delete(workspace_id, confirm)

    @mcp.tool()
    @_wrap
    async def list_files(workspace_id: str, subdir: str = "") -> dict:
        return app.workspaces.list_files(workspace_id, subdir)

    @mcp.tool()
    @_wrap
    async def read_file(workspace_id: str, path: str) -> dict:
        return app.workspaces.read_file(workspace_id, path)

    @mcp.tool()
    @_wrap
    async def write_file(workspace_id: str, path: str, content: str) -> dict:
        """Create/overwrite a UTF-8 text file inside a workspace."""
        return app.workspaces.write_file(workspace_id, path, content)

    @mcp.tool()
    @_wrap
    async def edit_file(workspace_id: str, path: str, old: str, new: str) -> dict:
        """Replace exactly one occurrence of `old` with `new`."""
        return app.workspaces.edit_file(workspace_id, path, old, new)

    @mcp.tool()
    @_wrap
    async def delete_file(workspace_id: str, path: str) -> dict:
        return app.workspaces.delete_file(workspace_id, path)

    @mcp.tool()
    @_wrap
    async def search_files(workspace_id: str, query: str) -> dict:
        return app.workspaces.search_files(workspace_id, query)

    # ---------- execution ----------
    @mcp.tool()
    @_wrap
    async def run_command(workspace_id: str, profile: str, argv: list[str] | None = None,
                          shell_script: str | None = None, network: str = "disabled",
                          timeout_seconds: int = 0, wait: bool = True) -> dict:
        """Run a command ONLY inside a hardened Docker container for `profile`.
        Prefer argv (no shell). shell_script runs via sh -c INSIDE the container.
        network: 'disabled' (default, no network) or 'approved' (plain bridge,
        unrestricted - explicit opt-in). Client cannot set images/mounts/flags."""
        return await app.tasks.submit(
            workspace_id=workspace_id, profile_name=profile, argv=argv,
            shell_script=shell_script, network=network,
            timeout_seconds=(timeout_seconds or None), wait=wait)

    @mcp.tool()
    @_wrap
    async def run_parallel(commands: list[dict]) -> dict:
        """Run several independent commands concurrently (bounded by
        MINSYNC_MAX_CONCURRENT_TASKS; same workspace serialized).
        Each item: {workspace_id, profile, argv|shell_script, network?, timeout_seconds?}"""
        if not isinstance(commands, list) or not commands or len(commands) > 16:
            raise InvalidArgument("commands must be a list of 1..16 items")
        results = await asyncio.gather(*[
            app.tasks.submit(
                workspace_id=c["workspace_id"], profile_name=c["profile"],
                argv=c.get("argv"), shell_script=c.get("shell_script"),
                network=c.get("network", "disabled"),
                timeout_seconds=c.get("timeout_seconds"), wait=True)
            for c in commands
        ], return_exceptions=True)
        out = []
        for r in results:
            if isinstance(r, MinSyncError):
                out.append({"ok": False, "error": r.to_dict()})
            elif isinstance(r, Exception):
                out.append({"ok": False, "error": {"code": "internal_error", "message": str(r)}})
            else:
                out.append(r)
        return {"results": out}

    @mcp.tool()
    @_wrap
    async def get_task_status(task_id: str) -> dict:
        return app.tasks.get(task_id, include_output=False)

    @mcp.tool()
    @_wrap
    async def get_task_output(task_id: str, stream: str = "stdout",
                              offset: int = 0, limit: int = 65536) -> dict:
        """Fetch a slice of task output (never an unbounded blob)."""
        return app.tasks.output(task_id, stream, offset, limit)

    @mcp.tool()
    @_wrap
    async def cancel_task(task_id: str) -> dict:
        return await app.tasks.cancel(task_id)

    @mcp.tool()
    @_wrap
    async def list_tasks(workspace_id: str = "") -> dict:
        return {"tasks": app.tasks.list(workspace_id or None)}

    # ---------- projects ----------
    async def _project_cmd(workspace_id: str, profile: str, kind: str, fn,
                           network: str, timeout_seconds: int) -> dict:
        root = app.workspaces.root(workspace_id)
        prof = profiles_mod.get_profile(profile)
        argv, shell = fn(prof, root)
        return await app.tasks.submit(
            workspace_id=workspace_id, profile_name=profile, argv=argv,
            shell_script=shell, kind=kind, network=network,
            timeout_seconds=(timeout_seconds or None), wait=True)

    @mcp.tool()
    @_wrap
    async def install_dependencies(workspace_id: str, profile: str,
                                   network: str = "approved", timeout_seconds: int = 600) -> dict:
        """Install project dependencies inside the container. Needs network,
        so network defaults to 'approved' (explicit, unrestricted bridge)."""
        return await _project_cmd(workspace_id, profile, "install", install_command,
                                  network, timeout_seconds)

    @mcp.tool()
    @_wrap
    async def build_project(workspace_id: str, profile: str, timeout_seconds: int = 600) -> dict:
        """Build the project inside its profile container (offline by default)."""
        return await _project_cmd(workspace_id, profile, "build", build_command,
                                  "disabled", timeout_seconds)

    @mcp.tool()
    @_wrap
    async def run_tests(workspace_id: str, profile: str, timeout_seconds: int = 600) -> dict:
        """Run the profile's test command inside the container."""
        return await _project_cmd(workspace_id, profile, "test", test_command,
                                  "disabled", timeout_seconds)

    # ---------- archives / artifacts ----------
    @mcp.tool()
    @_wrap
    async def upload_archive(workspace_id: str, filename: str, data_base64: str) -> dict:
        """Upload a ZIP (base64, <= MINSYNC_MAX_ARCHIVE_BYTES) into the workspace
        under .uploads/. Does not extract; call extract_archive explicitly."""
        if "/" in filename or "\\" in filename or not filename.endswith(".zip"):
            raise InvalidArgument("filename must be a plain *.zip name")
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise InvalidArgument("data_base64 is not valid base64") from None
        return app.workspaces.write_bytes(workspace_id, f".uploads/{filename}", data)

    @mcp.tool()
    @_wrap
    async def extract_archive(workspace_id: str, archive_path: str, dest: str = "") -> dict:
        """Safely extract a ZIP from inside the workspace (Zip-Slip/bomb guards)."""
        return app.archives.extract_archive(workspace_id, archive_path, dest)

    @mcp.tool()
    @_wrap
    async def create_archive(workspace_id: str, name: str = "") -> dict:
        """Zip the workspace into a stored artifact (id, size, sha256, local path)."""
        return app.archives.create_archive(workspace_id, name or None)

    @mcp.tool()
    @_wrap
    async def list_artifacts(workspace_id: str = "") -> dict:
        return {"artifacts": app.archives.list_artifacts(workspace_id or None)}

    @mcp.tool()
    @_wrap
    async def get_artifact(artifact_id: str, include_base64: bool = False) -> dict:
        """Artifact metadata + local path; base64 only if requested and <=512KiB.
        No fake download URLs are ever returned."""
        return app.archives.get_artifact(artifact_id, include_base64)

    mcp._minsync_app = app  # type: ignore[attr-defined]
    return mcp


def main_stdio() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    create_server().run(transport="stdio")
