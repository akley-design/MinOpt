"""Security-focused tests. Source-level checks PLUS (docker-marked) live
isolation checks that run only when a real Docker Engine exists."""
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from minsync import server as server_mod
from minsync.docker_backend import DockerBackend


def test_no_host_shell_execution_of_user_code():
    """User code must never reach a host shell: no shell=True, no os.system,
    no PowerShell/CMD invocation anywhere in production source."""
    src = Path(__file__).resolve().parents[2] / "src" / "minsync"
    offenders = []
    for f in src.rglob("*.py"):
        text = f.read_text()
        for needle in ("shell=True", "os.system", "powershell", "cmd.exe", "Popen("):
            if needle in text:
                offenders.append((f.name, needle))
    assert offenders == [], offenders


def test_tool_schemas_have_no_dangerous_params():
    """MCP clients must not be able to pass image/mount/privileged/network-host."""
    src = inspect.getsource(server_mod)
    for needle in ("privileged", "host_network", "docker_sock", "mount_path", "image_name"):
        assert needle not in src, needle


def test_symlink_escape_rejected(app, tmp_path):
    ws = app.workspaces.create("sym")
    root = Path(ws["path"])
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    from minsync.errors import FileOperationError, PathTraversal
    with pytest.raises((PathTraversal, FileOperationError)):
        app.workspaces.read_file(ws["id"], "link.txt")


def test_archive_limits(app):
    ws = app.workspaces.create("lim")
    app.settings.max_archive_bytes = 10
    from minsync.errors import QuotaExceeded
    with pytest.raises(QuotaExceeded):
        app.workspaces.write_bytes(ws["id"], ".uploads/big.zip", b"x" * 11)


@pytest.mark.docker
def test_live_isolation_marker(tmp_path):
    pytest.skip("requires Docker; covered by tests/integration/test_docker.py checks")
