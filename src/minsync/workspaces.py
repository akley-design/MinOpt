"""Workspace management + safe file operations inside a workspace.

Traversal rule (security-critical): symlinked directories are NEVER
descended into. Containers can create symlinks inside their workspace;
following them on the host (inspect/quota/search/archive) could read or
zip files outside the workspace. All walks go through iter_files().
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
from pathlib import Path

from .config import Settings
from .errors import FileOperationError, InvalidArgument, QuotaExceeded, WorkspaceNotFound
from .security_paths import resolve_within, validate_id
from .storage import Storage

_NAME_RE = re.compile(r"^[A-Za-z0-9 _.-]{1,64}$")

# Dependency caches created by MinSync's own install step: persisted for
# reuse across one-shot containers, but excluded from project archives.
ARCHIVE_EXCLUDED_DIRS = {".minsync_deps", ".cache", "__pycache__", ".pytest_cache"}


def iter_files(root: Path):
    """Yield regular (non-symlink) files under root, pruning symlinked dirs."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                yield p


def iter_entries(root: Path, base: Path):
    """Yield (path, kind) for files/dirs/symlinks under base without
    descending into symlinked directories."""
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        real_dirs = []
        for d in dirnames:
            p = Path(dirpath) / d
            yield p, ("symlink" if p.is_symlink() else "dir")
            if not p.is_symlink():
                real_dirs.append(d)
        dirnames[:] = real_dirs
        for name in filenames:
            p = Path(dirpath) / name
            yield p, ("symlink" if p.is_symlink() else "file")


class WorkspaceManager:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage

    # ------------------------------------------------------------------
    def root(self, workspace_id: str) -> Path:
        validate_id(workspace_id, "workspace_id")
        if not self.storage.get_workspace(workspace_id):
            raise WorkspaceNotFound(f"unknown workspace: {workspace_id}")
        return self.settings.workspaces_dir / workspace_id

    def create(self, name: str = "workspace", profile: str | None = None) -> dict:
        if not _NAME_RE.match(name or ""):
            raise InvalidArgument("workspace name: 1-64 chars, letters/digits/space/_.- only")
        wid = "ws_" + secrets.token_hex(6)
        (self.settings.workspaces_dir / wid).mkdir(parents=True, exist_ok=False)
        self.storage.add_workspace(wid, name, profile)
        return self.inspect(wid)

    def inspect(self, workspace_id: str) -> dict:
        meta = self.storage.get_workspace(workspace_id)
        if not meta:
            raise WorkspaceNotFound(f"unknown workspace: {workspace_id}")
        root = self.settings.workspaces_dir / workspace_id
        total, count = 0, 0
        for p in iter_files(root):
            try:
                total += p.stat().st_size
                count += 1
            except OSError:
                continue
        return {**meta, "path": str(root), "file_count": count, "size_bytes": total}

    def list(self) -> list[dict]:
        return [self.inspect(w["id"]) for w in self.storage.list_workspaces()]

    def delete(self, workspace_id: str, confirm: bool) -> dict:
        if confirm is not True:
            raise InvalidArgument(
                "delete_workspace requires confirm=true; this permanently deletes project files"
            )
        active = [
            t["id"]
            for t in self.storage.list_tasks(workspace_id, limit=200)
            if t["status"] in ("queued", "running", "cancelling")
        ]
        if active:
            raise InvalidArgument(f"workspace has active tasks {active}; cancel them before deleting")
        root = self.root(workspace_id)
        shutil.rmtree(root, ignore_errors=True)
        self.storage.delete_workspace(workspace_id)
        return {"deleted": workspace_id}

    # ------------------------------------------------------------------
    def list_files(self, workspace_id: str, subdir: str = "", max_entries: int = 1000) -> dict:
        root = self.root(workspace_id)
        base = resolve_within(root, subdir) if subdir else root
        if not base.exists():
            raise FileOperationError(f"directory does not exist: {subdir!r}")
        if base.is_symlink() or not base.is_dir():
            raise FileOperationError(f"not a directory: {subdir!r}")
        entries = []
        truncated = False
        for p, kind in iter_entries(root, base):
            if len(entries) >= max_entries:
                truncated = True
                break
            size = None
            if kind == "file":
                try:
                    size = p.stat().st_size
                except OSError:
                    pass
            entries.append({"path": str(p.relative_to(root)).replace("\\", "/"), "type": kind, "size": size})
        entries.sort(key=lambda e: e["path"])
        return {"workspace_id": workspace_id, "entries": entries, "truncated": truncated}

    def read_file(self, workspace_id: str, path: str, max_bytes: int | None = None) -> dict:
        root = self.root(workspace_id)
        f = resolve_within(root, path, must_exist=True)
        if not f.is_file() or f.is_symlink():
            raise FileOperationError(f"not a regular file: {path!r}")
        limit = max(1, max_bytes) if max_bytes else self.settings.max_file_bytes
        with open(f, "rb") as fh:
            data = fh.read(limit + 1)
        truncated = len(data) > limit
        try:
            text = data[:limit].decode("utf-8")
        except UnicodeDecodeError:
            raise FileOperationError(f"file is not UTF-8 text: {path!r}") from None
        return {"workspace_id": workspace_id, "path": path, "content": text, "truncated": truncated}

    def _check_quota(self, root: Path, additional: int) -> None:
        total = 0
        for p in iter_files(root):
            try:
                total += p.stat().st_size
            except OSError:
                continue
        if total + additional > self.settings.max_workspace_bytes:
            raise QuotaExceeded(f"workspace quota exceeded ({self.settings.max_workspace_bytes} bytes)")

    def _write(self, workspace_id: str, path: str, data: bytes, limit: int, what: str) -> dict:
        root = self.root(workspace_id)
        if len(data) > limit:
            raise QuotaExceeded(f"{what} exceeds {limit} bytes")
        f = resolve_within(root, path)
        self._check_quota(root, len(data))
        f.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after mkdir: a symlinked parent must not escape.
        f = resolve_within(root, path)
        if f.is_symlink():
            raise FileOperationError("refusing to write through a symlink")
        tmp = f.with_name(f".{f.name}.{secrets.token_hex(4)}.minsync-tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, f)  # atomic-ish: no half-written files on crash
        finally:
            tmp.unlink(missing_ok=True)
        return {"workspace_id": workspace_id, "path": path, "size": len(data)}

    def write_file(self, workspace_id: str, path: str, content: str) -> dict:
        return self._write(workspace_id, path, content.encode("utf-8"), self.settings.max_file_bytes, "file")

    def write_bytes(self, workspace_id: str, path: str, data: bytes) -> dict:
        return self._write(workspace_id, path, data, self.settings.max_archive_bytes, "upload")

    def edit_file(self, workspace_id: str, path: str, old: str, new: str) -> dict:
        if not old:
            raise InvalidArgument("edit_file: `old` must be non-empty")
        cur = self.read_file(workspace_id, path)
        if cur["truncated"]:
            raise FileOperationError("file too large to edit safely")
        if cur["content"].count(old) != 1:
            raise FileOperationError("edit_file requires exactly one occurrence of `old`")
        return self.write_file(workspace_id, path, cur["content"].replace(old, new, 1))

    def delete_file(self, workspace_id: str, path: str) -> dict:
        root = self.root(workspace_id)
        f = resolve_within(root, path, must_exist=True)
        if f == root.resolve():
            raise InvalidArgument("use delete_workspace to delete the whole workspace")
        if f.is_dir() and not f.is_symlink():
            shutil.rmtree(f)
        else:
            f.unlink()
        return {"deleted": path}

    def search_files(self, workspace_id: str, query: str, max_results: int = 100) -> dict:
        root = self.root(workspace_id)
        if not query or len(query) > 500:
            raise InvalidArgument("query must be 1-500 chars")
        results = []
        for p in sorted(iter_files(root)):
            if len(results) >= max_results:
                break
            try:
                if p.stat().st_size > self.settings.max_file_bytes:
                    continue
                lines = p.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines, 1):
                if query in line:
                    results.append(
                        {"path": str(p.relative_to(root)).replace("\\", "/"), "line": i, "text": line[:300]}
                    )
                    if len(results) >= max_results:
                        break
        return {"workspace_id": workspace_id, "results": results, "truncated": len(results) >= max_results}
