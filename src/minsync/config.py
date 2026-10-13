"""MinSync configuration. Values come from environment variables only;
secrets are never logged and never passed to containers by default."""
from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    env = os.environ.get("MINSYNC_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "MinSync"
    return Path.home() / ".local" / "share" / "minsync"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    max_concurrent_tasks: int = field(default_factory=lambda: _int("MINSYNC_MAX_CONCURRENT_TASKS", 2))
    task_timeout_seconds: int = field(default_factory=lambda: _int("MINSYNC_TASK_TIMEOUT_SECONDS", 120))
    max_timeout_seconds: int = field(default_factory=lambda: _int("MINSYNC_MAX_TIMEOUT_SECONDS", 900))
    memory_mb: int = field(default_factory=lambda: _int("MINSYNC_MEMORY_MB", 512))
    cpus: float = field(default_factory=lambda: _float("MINSYNC_CPUS", 1.0))
    pids_limit: int = field(default_factory=lambda: _int("MINSYNC_PIDS_LIMIT", 128))
    max_output_bytes: int = field(default_factory=lambda: _int("MINSYNC_MAX_OUTPUT_BYTES", 262_144))
    max_file_bytes: int = field(default_factory=lambda: _int("MINSYNC_MAX_FILE_BYTES", 5_242_880))
    max_workspace_bytes: int = field(default_factory=lambda: _int("MINSYNC_MAX_WORKSPACE_BYTES", 209_715_200))
    max_archive_bytes: int = field(default_factory=lambda: _int("MINSYNC_MAX_ARCHIVE_BYTES", 20_971_520))
    max_uncompressed_bytes: int = field(default_factory=lambda: _int("MINSYNC_MAX_UNCOMPRESSED_BYTES", 104_857_600))
    max_artifact_bytes: int = field(default_factory=lambda: _int("MINSYNC_MAX_ARTIFACT_BYTES", 52_428_800))
    max_archive_files: int = field(default_factory=lambda: _int("MINSYNC_MAX_ARCHIVE_FILES", 2000))
    max_archive_depth: int = field(default_factory=lambda: _int("MINSYNC_MAX_ARCHIVE_DEPTH", 20))
    task_retention_days: int = field(default_factory=lambda: _int("MINSYNC_TASK_RETENTION_DAYS", 7))
    docker_dir: str = field(default_factory=lambda: os.environ.get("MINSYNC_DOCKER_DIR", ""))
    # 'disabled' (default, --network none) or 'approved' (plain bridge, explicit opt-in).
    # There is intentionally no fake 'restricted' mode: no verified egress proxy ships in v1.
    default_network: str = field(default_factory=lambda: os.environ.get("MINSYNC_DEFAULT_NETWORK", "disabled"))

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def db_path(self) -> Path:
        return self.state_dir / "minsync.db"

    def ensure_dirs(self) -> None:
        for d in (self.workspaces_dir, self.artifacts_dir, self.logs_dir, self.state_dir):
            d.mkdir(parents=True, exist_ok=True)

    def public_dict(self) -> dict:
        return {
            "data_dir": str(self.data_dir),
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "task_timeout_seconds": self.task_timeout_seconds,
            "max_timeout_seconds": self.max_timeout_seconds,
            "memory_mb": self.memory_mb,
            "cpus": self.cpus,
            "pids_limit": self.pids_limit,
            "max_output_bytes": self.max_output_bytes,
            "max_file_bytes": self.max_file_bytes,
            "max_archive_bytes": self.max_archive_bytes,
            "max_artifact_bytes": self.max_artifact_bytes,
            "default_network": self.default_network,
        }
