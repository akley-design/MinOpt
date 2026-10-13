"""ZIP creation/extraction with Zip-Slip, symlink and zip-bomb protection,
plus artifact bookkeeping (size + SHA-256).

Extraction enforces limits on ACTUAL bytes written (not only header
claims) and deletes a partial file if a limit is hit mid-entry.
Creation never follows symlinks and excludes MinSync dependency caches.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import zipfile
from pathlib import Path

from .config import Settings
from .errors import ArchiveError, ArtifactNotFound, QuotaExceeded
from .security_paths import resolve_within
from .storage import Storage
from .workspaces import ARCHIVE_EXCLUDED_DIRS, WorkspaceManager, iter_files


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ArchiveManager:
    def __init__(self, settings: Settings, storage: Storage, workspaces: WorkspaceManager):
        self.settings = settings
        self.storage = storage
        self.workspaces = workspaces

    def create_archive(self, workspace_id: str, name: str | None = None, task_id: str | None = None) -> dict:
        root = self.workspaces.root(workspace_id)
        aid = "art_" + secrets.token_hex(6)
        filename = name or f"{workspace_id}.zip"
        if (
            not filename.endswith(".zip")
            or "/" in filename
            or "\\" in filename
            or filename in (".zip", "..zip")
        ):
            raise ArchiveError("artifact name must be a plain *.zip filename")
        out_dir = self.settings.artifacts_dir / workspace_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{aid}_{filename}"
        total = 0
        try:
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in iter_files(root):
                    rel = p.relative_to(root)
                    if any(part in ARCHIVE_EXCLUDED_DIRS for part in rel.parts):
                        continue
                    try:
                        total += p.stat().st_size
                    except OSError:
                        continue
                    if total > self.settings.max_artifact_bytes:
                        raise QuotaExceeded("archive exceeds max artifact size")
                    zf.write(p, str(rel).replace("\\", "/"))
        except Exception:
            out_path.unlink(missing_ok=True)
            raise
        art = {
            "id": aid,
            "workspace_id": workspace_id,
            "task_id": task_id,
            "filename": filename,
            "size": out_path.stat().st_size,
            "sha256": _hash_file(out_path),
            "created_at": time.time(),
            "path": str(out_path),
        }
        self.storage.add_artifact(art)
        return {
            k: art[k]
            for k in ("id", "workspace_id", "task_id", "filename", "size", "sha256", "created_at", "path")
        }

    def extract_archive(self, workspace_id: str, archive_path: str, dest: str = "") -> dict:
        s = self.settings
        root = self.workspaces.root(workspace_id)
        src = resolve_within(root, archive_path, must_exist=True)
        if src.is_symlink() or not src.is_file():
            raise ArchiveError(f"not a regular file: {archive_path!r}")
        if src.stat().st_size > s.max_archive_bytes:
            raise QuotaExceeded(f"archive exceeds {s.max_archive_bytes} bytes")
        dest_root = resolve_within(root, dest) if dest else root
        extracted, total, written_total = [], 0, 0
        try:
            zf = zipfile.ZipFile(src)
        except zipfile.BadZipFile:
            raise ArchiveError(f"not a valid ZIP file: {archive_path!r}") from None
        with zf:
            infos = zf.infolist()
            if len(infos) > s.max_archive_files:
                raise ArchiveError(f"archive has too many files (>{s.max_archive_files})")
            for info in infos:
                name = info.filename
                if name.endswith("/"):
                    continue
                if not name or "\x00" in name:
                    raise ArchiveError("empty or invalid entry name in archive")
                depth = len([p for p in name.replace("\\", "/").split("/") if p])
                if depth > s.max_archive_depth:
                    raise ArchiveError(f"archive path too deep: {name!r}")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ArchiveError(f"symlink entries are not allowed: {name!r}")
                if info.compress_size and info.file_size / max(info.compress_size, 1) > 200:
                    raise ArchiveError(f"suspicious compression ratio: {name!r}")
                total += info.file_size
                if total > s.max_uncompressed_bytes:
                    raise ArchiveError("uncompressed size exceeds limit (possible zip bomb)")
                target = resolve_within(dest_root, name)  # Zip-Slip guard
                target.parent.mkdir(parents=True, exist_ok=True)
                target = resolve_within(dest_root, name)
                if target.is_symlink():
                    raise ArchiveError(f"refusing to overwrite symlink: {name!r}")
                if target.exists() and target.is_dir():
                    raise ArchiveError(f"entry collides with a directory: {name!r}")
                written = 0
                try:
                    with zf.open(info) as fh, open(target, "wb") as out:
                        while chunk := fh.read(65536):
                            written += len(chunk)
                            written_total += len(chunk)
                            if (
                                written > info.file_size and info.file_size >= 0
                            ) or written_total > s.max_uncompressed_bytes:
                                raise ArchiveError("actual decompressed size exceeds declared limit")
                            out.write(chunk)
                except ArchiveError:
                    target.unlink(missing_ok=True)
                    raise
                except (zipfile.BadZipFile, RuntimeError, OSError) as e:
                    target.unlink(missing_ok=True)
                    raise ArchiveError(f"failed to extract {name!r}: {e}") from None
                extracted.append(name)
        return {"workspace_id": workspace_id, "extracted": extracted, "count": len(extracted)}

    def list_artifacts(self, workspace_id: str | None = None) -> list[dict]:
        return [
            {
                k: a[k]
                for k in ("id", "workspace_id", "task_id", "filename", "size", "sha256", "created_at", "path")
            }
            for a in self.storage.list_artifacts(workspace_id)
        ]

    def get_artifact(self, artifact_id: str, include_base64: bool = False) -> dict:
        a = self.storage.get_artifact(artifact_id)
        if not a:
            raise ArtifactNotFound(f"unknown artifact: {artifact_id}")
        out = {
            k: a[k]
            for k in ("id", "workspace_id", "task_id", "filename", "size", "sha256", "created_at", "path")
        }
        # Local clients get a real filesystem path. Content is only inlined
        # when explicitly requested and small - never a giant MCP text blob,
        # never a fake download URL.
        if include_base64:
            p = Path(a["path"])
            if not p.exists():
                raise ArtifactNotFound("artifact file is missing on disk")
            if p.stat().st_size > 524_288:
                raise QuotaExceeded("artifact too large for inline base64 (>512 KiB); use the local path")
            out["content_base64"] = base64.b64encode(p.read_bytes()).decode()
        return out
