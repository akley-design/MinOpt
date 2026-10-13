import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from minsync.app import MinSyncApp
from minsync.config import Settings
from minsync.docker_backend import ExecResult


class FakeBackend:
    """Test-only backend. Never used by production code (server defaults to
    DockerBackend). Simulates outcomes WITHOUT executing user code on host."""

    def __init__(self):
        self.cancelled = set()

    async def diagnostics(self):
        return {"available": True, "cli": "fake-for-tests", "fake": True}

    async def cancel(self, task_id):
        self.cancelled.add(task_id)
        return True

    async def run(self, *, profile, workspace_dir, task_id, command_argv,
                  network, timeout_seconds):
        started = time.monotonic()
        joined = " ".join(command_argv)
        if "sleep" in joined:
            secs = float(command_argv[-1]) if command_argv[-1].replace(".", "").isdigit() else 5
            if secs > timeout_seconds:
                await asyncio.sleep(timeout_seconds)
                return ExecResult(None, "", "", duration_ms=timeout_seconds * 1000, timed_out=True)
            await asyncio.sleep(secs)
            if task_id in self.cancelled:
                return ExecResult(130, "", "", duration_ms=1, cancelled=True)
        if task_id in self.cancelled:
            return ExecResult(130, "", "", duration_ms=1, cancelled=True)
        if "fail" in joined:
            return ExecResult(3, "", "boom on stderr", duration_ms=5)
        if "big" in joined:
            return ExecResult(0, "x" * 5000, "", duration_ms=5)
        return ExecResult(0, f"ran:{joined}", "", duration_ms=int((time.monotonic() - started) * 1000))


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def app(settings):
    return MinSyncApp(settings, backend=FakeBackend())
