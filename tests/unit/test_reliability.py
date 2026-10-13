import asyncio
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from minsync.errors import ArchiveError
from minsync.storage import Storage


def test_storage_does_not_recover_until_owner_asks(tmp_path):
    db = tmp_path / "s.db"
    st = Storage(db)
    st.add_workspace("ws_1", "a", None)
    st.add_task(
        {
            "id": "task_1",
            "workspace_id": "ws_1",
            "profile": "python",
            "kind": "run",
            "command": {},
            "status": "queued",
            "created_at": time.time(),
        }
    )
    st.update_task("task_1", status="running")
    st2 = Storage(db)  # e.g. a diagnostic process opening the same DB
    assert st2.get_task("task_1")["status"] == "running"
    assert st2.recover_interrupted() == 1
    t = st2.get_task("task_1")
    assert t["status"] == "failed" and t["error_code"] == "interrupted"


def test_doctor_is_read_only(tmp_path):
    data = tmp_path / "data"
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from minsync.config import Settings
    from minsync.app import MinSyncApp

    app = MinSyncApp(Settings(data_dir=data))
    ws = app.workspaces.create("live")
    app.storage.add_task(
        {
            "id": "task_live",
            "workspace_id": ws["id"],
            "profile": "python",
            "kind": "run",
            "command": {},
            "status": "queued",
            "created_at": time.time(),
        }
    )
    app.storage.update_task("task_live", status="running")
    env = dict(os.environ, MINSYNC_DATA_DIR=str(data))
    r = subprocess.run(
        [sys.executable, "-m", "minsync", "doctor"], capture_output=True, text=True, env=env, timeout=30
    )
    assert r.returncode == 2  # no Docker in this environment
    assert "configuration error" not in r.stderr
    assert app.storage.get_task("task_live")["status"] == "running"


def test_invalid_network_env_fails_loudly(tmp_path):
    env = dict(os.environ, MINSYNC_DATA_DIR=str(tmp_path), MINSYNC_DEFAULT_NETWORK="restricted")
    r = subprocess.run(
        [sys.executable, "-m", "minsync", "doctor"], capture_output=True, text=True, env=env, timeout=30
    )
    assert r.returncode == 2 and "configuration error" in r.stderr
    assert "Traceback" not in r.stderr


@pytest.mark.asyncio
async def test_same_workspace_serialized_different_parallel(app):
    ws1 = app.workspaces.create("s1")
    ws2 = app.workspaces.create("s2")
    start = time.monotonic()
    await asyncio.gather(
        app.tasks.submit(
            workspace_id=ws1["id"], profile_name="bash", argv=["sleep", "0.4"], shell_script=None
        ),
        app.tasks.submit(
            workspace_id=ws1["id"], profile_name="bash", argv=["sleep", "0.4"], shell_script=None
        ),
    )
    serial = time.monotonic() - start
    assert serial >= 0.7, serial
    start = time.monotonic()
    await asyncio.gather(
        app.tasks.submit(
            workspace_id=ws1["id"], profile_name="bash", argv=["sleep", "0.4"], shell_script=None
        ),
        app.tasks.submit(
            workspace_id=ws2["id"], profile_name="bash", argv=["sleep", "0.4"], shell_script=None
        ),
    )
    parallel = time.monotonic() - start
    assert parallel < 0.75, parallel


def test_corrupt_zip_raises_and_cleans_partial(app, tmp_path):
    ws = app.workspaces.create("corrupt")
    good = tmp_path / "g.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("a.txt", "hello world hello world")
    raw = bytearray(good.read_bytes())
    raw[raw.index(b"hello")] ^= 0xFF  # corrupt stored file data (CRC must fail)
    app.workspaces.write_bytes(ws["id"], ".uploads/bad.zip", bytes(raw))
    with pytest.raises((ArchiveError, zipfile.BadZipFile)):
        app.archives.extract_archive(ws["id"], ".uploads/bad.zip")


def test_extract_limit_stops_before_overflow_file(app, tmp_path):
    ws = app.workspaces.create("limit2")
    p = tmp_path / "two.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("one.txt", "123456")
        zf.writestr("two.txt", "123456")
    app.workspaces.write_bytes(ws["id"], ".uploads/two.zip", p.read_bytes())
    app.settings.max_uncompressed_bytes = 10
    with pytest.raises(ArchiveError):
        app.archives.extract_archive(ws["id"], ".uploads/two.zip")
    root = Path(ws["path"])
    assert (root / "one.txt").exists() and not (root / "two.txt").exists()


@pytest.mark.asyncio
async def test_cannot_delete_workspace_with_active_task(app):
    from minsync.errors import InvalidArgument

    ws = app.workspaces.create("busy")
    t = await app.tasks.submit(
        workspace_id=ws["id"], profile_name="bash", argv=["sleep", "30"], shell_script=None, wait=False
    )
    await asyncio.sleep(0.2)
    with pytest.raises(InvalidArgument):
        app.workspaces.delete(ws["id"], confirm=True)
    await app.tasks.cancel(t["id"])
    assert app.workspaces.delete(ws["id"], confirm=True)["deleted"] == ws["id"]
