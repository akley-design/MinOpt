"""Workspace management + safe file operations inside a workspace."""
from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path

from .config import Settings
from .errors import FileOperationError, InvalidArgument, QuotaExceeded, WorkspaceNotFound
from .security_paths import resolve_within, validate_id
from .storage import Storage

_NAME_RE = re.compile(r"^[A-Za-z0-9 _.-]{1,64}$")


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
        for p in root.rglob("*"):
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
                count += 1
        return {**meta, "path": str(root), "file_count": count, "size_bytes": total}

    def list(self) -> list[dict]:
        return [self.inspect(w["id"]) for w in self.storage.list_workspaces()]

    def delete(self, workspace_id: str, confirm: bool) -> dict:
        if confirm is not True:
            raise InvalidArgument(
                "delete_workspace requires confirm=true; this permanently deletes project files")
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
        entries = []
        truncated = False
        for p in sorted(base.rglob("*")):
            if len(entries) >= max_entries:
                truncated = True
                break
            rel = str(p.relative_to(root)).replace("\\", "/")
            entries.append({
                "path": rel, "type": "symlink" if p.is_symlink() else ("dir" if p.is_dir() else "file"),
                "size": (p.stat().st_size if p.is_file() and not p.is_symlink() else None),
            })
        return {"workspace_id": workspace_id, "entries": entries, "truncated": truncated}

    def read_file(self, workspace_id: str, path: str, max_bytes: int | None = None) -> dict:
        root = self.root(workspace_id)
        f = resolve_within(root, path, must_exist=True)
        if not f.is_file() or f.is_symlink():
            raise FileOperationError(f"not a regular file: {path!r}")
        limit = max_bytes or self.settings.max_file_bytes
        data = f.read_bytes()[: limit + 1]
        truncated = len(data) > limit
        try:
            text = data[:limit].decode("utf-8")
        except UnicodeDecodeError:
            raise FileOperationError(f"file is not UTF-8 text: {path!r}") from None
        return {"workspace_id": workspace_id, "path": path, "content": text, "truncated": truncated}

    def _check_quota(self, root: Path, additional: int) -> None:
        total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())
        if total + additional > self.settings.max_workspace_bytes:
            raise QuotaExceeded(
                f"workspace quota exceeded ({self.settings.max_workspace_bytes} bytes)")

    def write_file(self, workspace_id: str, path: str, content: str) -> dict:
        root = self.root(workspace_id)
        data = content.encode("utf-8")
        if len(data) > self.settings.max_file_bytes:
            raise QuotaExceeded(f"file exceeds {self.settings.max_file_bytes} bytes")
        f = resolve_within(root, path)
        self._check_quota(root, len(data))
        f.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after mkdir: a symlinked parent must not escape.
        f = resolve_within(root, path)
        if f.is_symlink():
            raise FileOperationError("refusing to write through a symlink")
        f.write_bytes(data)
        return {"workspace_id": workspace_id, "path": path, "size": len(data)}

    def write_bytes(self, workspace_id: str, path: str, data: bytes) -> dict:
        root = self.root(workspace_id)
        if len(data) > self.settings.max_archive_bytes:
            raise QuotaExceeded(f"upload exceeds {self.settings.max_archive_bytes} bytes")
        f = resolve_within(root, path)
        self._check_quota(root, len(data))
        f.parent.mkdir(parents=True, exist_ok=True)
        f = resolve_within(root, path)
        if f.is_symlink():
            raise FileOperationError("refusing to write through a symlink")
        f.write_bytes(data)
        return {"workspace_id": workspace_id, "path": path, "size": len(data)}

    def edit_file(self, workspace_id: str, path: str, old: str, new: str) -> dict:
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
        for p in sorted(root.rglob("*")):
            if len(results) >= max_results:
                break
            if not p.is_file() or p.is_symlink() or p.stat().st_size > self.settings.max_file_bytes:
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines, 1):
                if query in line:
                    results.append({
                        "path": str(p.relative_to(root)).replace("\\", "/"),
                        "line": i, "text": line[:300]})
                    if len(results) >= max_results:
                        break
        return {"workspace_id": workspace_id, "results": results, "truncated": len(results) >= max_results}
