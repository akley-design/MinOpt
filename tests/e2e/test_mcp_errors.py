"""MCP error surface over real stdio: bad input must come back as structured
errors, never crash the session or escape onto the host."""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_stdio_error_surface(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["MINSYNC_DATA_DIR"] = str(tmp_path / "data")
    env["PYTHONPATH"] = str(ROOT / "src")
    params = StdioServerParameters(command=sys.executable, args=["-m", "minsync", "serve"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, **kw):
                r = await session.call_tool(tool, kw)
                return json.loads("".join(getattr(c, "text", "") for c in r.content))

            ws = await call("create_workspace", name="errs", profile="python")
            wid = ws["id"]

            bad_path = await call("write_file", workspace_id=wid, path="../evil.txt", content="x")
            assert bad_path["ok"] is False and bad_path["error"]["code"] == "path_traversal"

            unknown_ws = await call("read_file", workspace_id="ws_nope", path="a.txt")
            assert unknown_ws["ok"] is False and unknown_ws["error"]["code"] == "workspace_not_found"

            unknown_task = await call("get_task_status", task_id="task_nope")
            assert unknown_task["ok"] is False and unknown_task["error"]["code"] == "task_not_found"

            both = await call(
                "run_command", workspace_id=wid, profile="python", argv=["x"], shell_script="echo hi"
            )
            assert both.get("ok") is False and both["error"]["code"] == "invalid_argument", both

            bad_parallel = await call("run_parallel", commands=[{"profile": "python"}])
            assert bad_parallel["ok"] is False
            assert bad_parallel["error"]["code"] == "invalid_argument"

            unknown_profile = await call("run_command", workspace_id=wid, profile="cobol", argv=["x"])
            assert unknown_profile["ok"] is False
            assert unknown_profile["error"]["code"] == "unknown_profile"

            # session still alive after all errors
            alive = await call("health_check")
            assert alive["ok"] is True

            # delete guard: no confirm -> refused; with confirm -> works
            no = await call("delete_workspace", workspace_id=wid, confirm=False)
            assert no["ok"] is False
            yes = await call("delete_workspace", workspace_id=wid, confirm=True)
            assert yes["ok"] is True
