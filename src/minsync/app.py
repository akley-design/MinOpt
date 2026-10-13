"""Application assembly (modular monolith wiring)."""

from __future__ import annotations

import platform
import sys

from .archives import ArchiveManager
from .config import Settings
from .docker_backend import DockerBackend
from .storage import Storage
from .tasks import TaskManager
from .workspaces import WorkspaceManager

VERSION = "1.0.0"


def _health_payload(settings: Settings, docker: dict) -> dict:
    return {
        "ok": True,
        "service": "minsync",
        "version": VERSION,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "docker": docker,
        "execution_ready": bool(docker.get("available")),
        "note": (
            "ready"
            if docker.get("available")
            else "Docker Engine unavailable: workspace/file/archive tools work, "
            "run_command will return docker_unavailable with diagnostics. "
            "No host-shell fallback exists by design."
        ),
        "settings": settings.public_dict(),
    }


async def standalone_health(settings: Settings | None = None) -> dict:
    """Read-only health check: no data dir creation, no DB access, no
    mutation of a possibly-running server's task state."""
    settings = settings or Settings()
    docker = await DockerBackend(settings).diagnostics()
    return _health_payload(settings, docker)


class MinSyncApp:
    def __init__(self, settings: Settings | None = None, backend=None):
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.storage = Storage(self.settings.db_path)
        self.workspaces = WorkspaceManager(self.settings, self.storage)
        self.backend = backend if backend is not None else DockerBackend(self.settings)
        self.tasks = TaskManager(self.settings, self.storage, self.workspaces, self.backend)
        self.archives = ArchiveManager(self.settings, self.storage, self.workspaces)

    async def health(self) -> dict:
        docker = await self.backend.diagnostics()
        return _health_payload(self.settings, docker)
