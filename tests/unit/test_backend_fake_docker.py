"""DockerBackend exercised against a fake `docker` CLI script placed on
PATH. This tests the backend's process management (argv, streaming,
truncation, timeout, cancellation) WITHOUT a real Docker Engine and is
never presented as real-container evidence (that is tests/integration).
"""

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from minsync.config import Settings
from minsync.docker_backend import DockerBackend
from minsync.profiles import get_profile

FAKE = r"""
import json, os, sys, time
state = os.environ["FAKE_DOCKER_STATE"]
args = sys.argv[1:]
with open(os.path.join(state, "calls.log"), "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:1] == ["version"]:
    print("24.0-fake"); sys.exit(0)
if args[:1] == ["info"]:
    print("linux/x86_64"); sys.exit(0)
if args[:2] == ["image", "inspect"]:
    sys.exit(0)
if args[:1] == ["kill"]:
    open(os.path.join(state, "killed-" + args[1]), "w").write("1"); sys.exit(0)
if args[:1] == ["run"]:
    name = args[args.index("--name") + 1]
    cmd = args[args.index("minsync/python:3.12") + 1:] if "minsync/python:3.12" in args else []
    joined = " ".join(cmd)
    if "sleep" in joined:
        for _ in range(600):
            if os.path.exists(os.path.join(state, "killed-" + name)):
                sys.exit(137)
            time.sleep(0.05)
        sys.exit(0)
    if "big" in joined:
        sys.stdout.write("x" * 10000); sys.stdout.flush()
        sys.exit(0)
    if "fail" in joined:
        sys.stderr.write("fake-stderr"); sys.exit(7)
    print("fake-stdout:" + joined)
    sys.exit(0)
sys.exit(0)
"""


@pytest.fixture
def backend(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "docker"
    script.write_text("#!" + sys.executable + "\n" + FAKE)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(state))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    settings = Settings(data_dir=tmp_path / "data", max_output_bytes=4096)
    ws = tmp_path / "ws"
    ws.mkdir()
    return DockerBackend(settings), ws, state


@pytest.mark.asyncio
async def test_backend_run_success_fail_truncate(backend):
    be, ws, state = backend
    prof = get_profile("python")
    r = await be.run(
        profile=prof,
        workspace_dir=ws,
        task_id="t1",
        command_argv=["python3", "main.py"],
        network="disabled",
        timeout_seconds=10,
    )
    assert r.exit_code == 0 and "fake-stdout" in r.stdout
    calls = [json.loads(x) for x in (state / "calls.log").read_text().splitlines()]
    run_argv = [c for c in calls if c[:1] == ["run"]][0]
    assert "--rm" in run_argv and "none" in run_argv

    bad = await be.run(
        profile=prof,
        workspace_dir=ws,
        task_id="t2",
        command_argv=["fail"],
        network="disabled",
        timeout_seconds=10,
    )
    assert bad.exit_code == 7 and "fake-stderr" in bad.stderr

    big = await be.run(
        profile=prof,
        workspace_dir=ws,
        task_id="t3",
        command_argv=["big"],
        network="disabled",
        timeout_seconds=10,
    )
    assert big.stdout_truncated and len(big.stdout.encode()) == 4096


@pytest.mark.asyncio
async def test_backend_timeout_preserves_partial_and_kills(backend):
    be, ws, state = backend
    r = await be.run(
        profile=get_profile("python"),
        workspace_dir=ws,
        task_id="t4",
        command_argv=["sleep", "30"],
        network="disabled",
        timeout_seconds=1,
    )
    assert r.timed_out and r.exit_code is None
    assert (state / "killed-minsync-t4").exists()


@pytest.mark.asyncio
async def test_backend_cancel(backend):
    be, ws, state = backend
    task = asyncio.create_task(
        be.run(
            profile=get_profile("python"),
            workspace_dir=ws,
            task_id="t5",
            command_argv=["sleep", "30"],
            network="disabled",
            timeout_seconds=60,
        )
    )
    await asyncio.sleep(0.5)
    assert await be.cancel("t5") is True
    r = await asyncio.wait_for(task, timeout=10)
    assert r.cancelled and r.exit_code is None
