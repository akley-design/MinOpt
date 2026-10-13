import zipfile

import pytest

from minsync.docker_backend import DockerBackend
from minsync.errors import InvalidArgument, PathTraversal, QuotaExceeded, WorkspaceNotFound
from minsync.profiles import get_profile
from minsync.security_paths import resolve_within


def test_paths_reject_traversal(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    for bad in ("../x", "/etc/passwd", "C:\\secret", "..\\x", "a/../../b", "a\x00b"):
        with pytest.raises(PathTraversal):
            resolve_within(root, bad)


def test_workspace_file_crud(app):
    ws = app.workspaces.create("demo", "python")
    wid = ws["id"]
    assert app.workspaces.write_file(wid, "src/main.py", "print(1)")["size"] == 8
    assert app.workspaces.read_file(wid, "src/main.py")["content"] == "print(1)"
    app.workspaces.edit_file(wid, "src/main.py", "1", "2")
    assert "2" in app.workspaces.read_file(wid, "src/main.py")["content"]
    assert app.workspaces.search_files(wid, "print")["results"]
    assert app.workspaces.list_files(wid)["entries"]
    with pytest.raises(PathTraversal):
        app.workspaces.read_file(wid, "../secret")
    with pytest.raises(WorkspaceNotFound):
        app.workspaces.read_file("ws_nope", "x")
    with pytest.raises(InvalidArgument):
        app.workspaces.delete(wid, confirm=False)
    assert app.workspaces.delete(wid, confirm=True)["deleted"] == wid


def test_file_quota(app):
    ws = app.workspaces.create("q")
    app.settings.max_file_bytes = 10
    with pytest.raises(QuotaExceeded):
        app.workspaces.write_file(ws["id"], "big.txt", "x" * 11)


@pytest.mark.asyncio
async def test_task_success_fail_output(app):
    ws = app.workspaces.create("t")
    ok = await app.tasks.submit(workspace_id=ws["id"], profile_name="python",
                                argv=["python3", "main.py"], shell_script=None)
    assert ok["status"] == "succeeded" and ok["stdout"].startswith("ran:")
    bad = await app.tasks.submit(workspace_id=ws["id"], profile_name="python",
                                 argv=["fail"], shell_script=None)
    assert bad["status"] == "failed" and bad["exit_code"] == 3 and "boom" in bad["stderr"]
    out = app.tasks.output(bad["id"], "stderr")
    assert out["content"] == "boom on stderr"
    again = app.tasks.get(ok["id"])  # result re-fetch without re-run
    assert again["id"] == ok["id"]


@pytest.mark.asyncio
async def test_task_validation(app):
    ws = app.workspaces.create("t2")
    with pytest.raises(InvalidArgument):
        await app.tasks.submit(workspace_id=ws["id"], profile_name="python",
                               argv=["x"], shell_script="echo hi")
    with pytest.raises(InvalidArgument):
        await app.tasks.submit(workspace_id=ws["id"], profile_name="python",
                               argv=[], shell_script=None)


@pytest.mark.asyncio
async def test_task_parallel_and_timeout(app):
    ws1 = app.workspaces.create("a"); ws2 = app.workspaces.create("b")
    import asyncio
    r = await asyncio.gather(
        app.tasks.submit(workspace_id=ws1["id"], profile_name="bash",
                         argv=["sleep", "0.2"], shell_script=None),
        app.tasks.submit(workspace_id=ws2["id"], profile_name="bash",
                         argv=["sleep", "0.2"], shell_script=None))
    assert all(x["status"] == "succeeded" for x in r)
    slow = await app.tasks.submit(workspace_id=ws1["id"], profile_name="bash",
                                  argv=["sleep", "5"], shell_script=None, timeout_seconds=1)
    # FakeBackend reports timed_out only when its sleep finishes; manager maps it.
    assert slow["status"] == "timed_out"


def test_archive_roundtrip_and_artifact(app, tmp_path):
    ws = app.workspaces.create("zip")
    app.workspaces.write_file(ws["id"], "a.txt", "hello")
    art = app.archives.create_archive(ws["id"])
    assert art["size"] > 0 and len(art["sha256"]) == 64
    ws2 = app.workspaces.create("zip2")
    # copy zip into ws2 via bytes (upload path)
    data = open(art["path"], "rb").read()
    app.workspaces.write_bytes(ws2["id"], ".uploads/in.zip", data)
    out = app.archives.extract_archive(ws2["id"], ".uploads/in.zip")
    assert "a.txt" in out["extracted"]
    assert app.workspaces.read_file(ws2["id"], "a.txt")["content"] == "hello"


def test_zip_slip_and_symlink_rejected(app, tmp_path):
    ws = app.workspaces.create("evil")
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../evil.txt", "pwned")
    app.workspaces.write_bytes(ws["id"], ".uploads/evil.zip", evil.read_bytes())
    with pytest.raises(PathTraversal):
        app.archives.extract_archive(ws["id"], ".uploads/evil.zip")
    assert not (tmp_path / "evil.txt").exists()


def test_docker_argv_hardening(settings, tmp_path):
    be = DockerBackend(settings)
    ws = tmp_path / "ws"; ws.mkdir()
    container, argv = be.build_run_argv(
        profile=get_profile("python"), workspace_dir=ws, task_id="task_1",
        command_argv=["python3", "main.py"], network="disabled")
    joined = " ".join(argv)
    assert "--cap-drop" in argv and "ALL" in argv
    assert "no-new-privileges" in joined and "--read-only" in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert "--privileged" not in argv and "docker.sock" not in joined
    assert "10001:10001" in argv
    # exactly one mount, and it is the workspace
    mounts = [a for a in argv if "type=bind" in a]
    assert len(mounts) == 1 and str(ws) in mounts[0]
    with pytest.raises(InvalidArgument):
        be.build_run_argv(profile=get_profile("python"), workspace_dir=ws,
                          task_id="t", command_argv=["x"], network="restricted")
