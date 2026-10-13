"""Real-Docker integration tests. Every test SKIPS (with reason) when no
Docker Engine is reachable - never a fake pass."""
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from minsync.app import MinSyncApp
from minsync.config import Settings

pytestmark = pytest.mark.docker


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                       capture_output=True, text=True, timeout=15)
    return r.returncode == 0


@pytest.fixture(scope="module")
def real_app(tmp_path_factory):
    if not _docker_ok():
        pytest.skip("Docker Engine not reachable (docker CLI/engine missing); "
                    "install Docker Desktop (Windows, WSL2) to run these tests")
    settings = Settings(data_dir=tmp_path_factory.mktemp("minsync-live"))
    return MinSyncApp(settings)  # real DockerBackend


@pytest.mark.asyncio
async def test_python_hello_stderr_exit_timeout_cancel(real_app):
    app = real_app
    ws = app.workspaces.create("live", "python")
    wid = ws["id"]
    app.workspaces.write_file(wid, "main.py", "print('hello-minsync')")
    r = await app.tasks.submit(workspace_id=wid, profile_name="python",
                               argv=["python3", "main.py"], shell_script=None)
    assert r["status"] == "succeeded" and "hello-minsync" in r["stdout"]

    app.workspaces.write_file(wid, "bad.py", "import sys; sys.stderr.write('oops'); sys.exit(7)")
    bad = await app.tasks.submit(workspace_id=wid, profile_name="python",
                                 argv=["python3", "bad.py"], shell_script=None)
    assert bad["status"] == "failed" and bad["exit_code"] == 7 and "oops" in bad["stderr"]

    slow = await app.tasks.submit(workspace_id=wid, profile_name="python",
                                  argv=["python3", "-c", "import time; time.sleep(30)"],
                                  shell_script=None, timeout_seconds=2)
    assert slow["status"] == "timed_out"

    long = await app.tasks.submit(workspace_id=wid, profile_name="python",
                                  argv=["python3", "-c", "import time; time.sleep(60)"],
                                  shell_script=None, wait=False)
    await asyncio.sleep(1)
    cancelled = await app.tasks.cancel(long["id"])
    assert cancelled["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cpp_and_node(real_app):
    app = real_app
    ws = app.workspaces.create("cpp", "cpp")
    app.workspaces.write_file(ws["id"], "main.cpp", '#include <cstdio>\nint main(){std::printf("cpp-ok");}')
    build = await app.tasks.submit(workspace_id=ws["id"], profile_name="cpp",
                                   argv=["g++", "-O2", "-o", "app", "main.cpp"], shell_script=None)
    assert build["status"] == "succeeded", build
    run = await app.tasks.submit(workspace_id=ws["id"], profile_name="cpp",
                                 argv=["./app"], shell_script=None)
    assert "cpp-ok" in run["stdout"]

    ws2 = app.workspaces.create("node", "node")
    app.workspaces.write_file(ws2["id"], "a.js", "console.log('node-ok')")
    js = await app.tasks.submit(workspace_id=ws2["id"], profile_name="node",
                                argv=["node", "a.js"], shell_script=None)
    assert "node-ok" in js["stdout"]


@pytest.mark.asyncio
async def test_host_marker_not_visible(real_app, tmp_path):
    """A marker file OUTSIDE the workspace must be invisible in-container."""
    marker = tmp_path / "HOST_MARKER.txt"
    marker.write_text("host-secret")
    ws = real_app.workspaces.create("iso", "python")
    r = await real_app.tasks.submit(
        workspace_id=ws["id"], profile_name="python",
        argv=["python3", "-c",
              "import os,sys; sys.exit(1 if os.path.exists('/HOST_MARKER.txt') or "
              "os.path.exists('/host_marker') else 0)"],
        shell_script=None)
    assert r["status"] == "succeeded"
    net = await real_app.tasks.submit(
        workspace_id=ws["id"], profile_name="python",
        argv=["python3", "-c",
              "import socket; socket.setdefaulttimeout(3); socket.create_connection(('1.1.1.1',53))"],
        shell_script=None, network="disabled")
    assert net["status"] == "failed"  # no network in disabled mode
