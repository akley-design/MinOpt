"""Path safety: workspaces are addressed by ID, files by workspace-relative
paths only. Absolute paths, drive letters, '..', NUL and symlink escapes are
rejected."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import InvalidArgument, PathTraversal

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_id(value: str, kind: str = "id") -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise InvalidArgument(f"invalid {kind}: {value!r}")
    return value


def resolve_within(root: Path, rel: str, *, must_exist: bool = False) -> Path:
    """Resolve `rel` under `root`, rejecting traversal and symlink escapes."""
    if not isinstance(rel, str) or "\x00" in rel:
        raise PathTraversal("path contains NUL or is not a string")
    # Reject absolute / Windows drive / UNC paths in any flavour.
    if PureWindowsPath(rel).is_absolute() or PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).drive:
        raise PathTraversal(f"absolute paths are not allowed: {rel!r}")
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PathTraversal(f"'..' is not allowed: {rel!r}")
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts) if parts else root_resolved
    # Walk existing ancestors: the nearest existing component must stay inside root
    # (catches symlinked directories pointing outside).
    probe = candidate
    while not probe.exists() and probe != root_resolved:
        probe = probe.parent
    try:
        probe.resolve().relative_to(root_resolved)
    except ValueError:
        raise PathTraversal(f"path escapes workspace via symlink: {rel!r}") from None
    if must_exist and not candidate.exists():
        raise InvalidArgument(f"file does not exist: {rel!r}")
    return candidate
