"""End-to-end via the REAL MCP stdio transport: spawn `minsync serve`,
list tools, call them through an MCP client session. Docker-dependent
execution is exercised only as a structured docker_unavailable error here
(the sandbox has no Docker); live execution is in tests/integration."""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TOOLS = {
    "minsync_info",
    "environment_info",
    "list_profiles",
    "health_check",
    "create_workspace",
    "list_workspaces",
    "inspect_workspace",
    "list_files",
    "read_file",
    "write_file",
    "edit_file",
    "search_files",
    "delete_workspace",
    "run_command",
    "run_parallel",
    "get_task_status",
    "get_task_output",
    "cancel_task",
    "install_dependencies",
    "build_project",
    "run_tests",
    "delete_file",
    "list_tasks",
    "upload_archive",
    "extract_archive",
    "create_archive",
    "list_artifacts",
    "get_artifact",
}


def _content_text(result):
    return "".join(getattr(c, "text", "") for c in result.content)


@pytest.mark.asyncio
async def test_stdio_full_flow(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["MINSYNC_DATA_DIR"] = str(tmp_path / "data")
    env["PYTHONPATH"] = str(ROOT / "src")
    params = StdioServerParameters(command=sys.executable, args=["-m", "minsync", "serve"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            missing = EXPECTED_TOOLS - names
            assert not missing, f"missing tools: {missing}"

            async def call(tool, **kw):
                r = await session.call_tool(tool, kw)
                return json.loads(_content_text(r))

            info = await call("health_check")
            assert info["ok"] is True and info["service"] == "minsync"

            ws = await call("create_workspace", name="e2e", profile="python")
            assert ws["ok"], ws
            wid = ws["id"]
            assert (await call("write_file", workspace_id=wid, path="main.py", content="print('hi')"))["ok"]
            assert "hi" in (await call("read_file", workspace_id=wid, path="main.py"))["content"]

            # No Docker in this environment -> structured error, NOT host exec, NOT crash.
            run = await call("run_command", workspace_id=wid, profile="python", argv=["python3", "main.py"])
            if not info["docker"]["available"]:
                assert run["status"] == "failed"
                assert run["error_code"] in ("docker_unavailable", "image_missing")

            art = await call("create_archive", workspace_id=wid)
            assert art["ok"] and art["sha256"]
            got = await call("get_artifact", artifact_id=art["id"])
            assert got["ok"] and Path(got["path"]).exists()

            # persistence across calls
            lst = await call("list_workspaces")
            assert any(w["id"] == wid for w in lst["workspaces"])
