"""SQLite (stdlib) metadata storage: workspaces, tasks, artifacts.
No external database. One connection guarded by a lock; short transactions."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, profile TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, profile TEXT, kind TEXT,
  command_json TEXT, status TEXT NOT NULL, created_at REAL, started_at REAL,
  finished_at REAL, exit_code INTEGER, stdout TEXT, stderr TEXT,
  stdout_truncated INTEGER, stderr_truncated INTEGER, duration_ms INTEGER,
  error_code TEXT, error_message TEXT);
CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY, workspace_id TEXT, task_id TEXT, filename TEXT,
  size INTEGER, sha256 TEXT, created_at REAL, path TEXT);
"""


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            # Recovery: tasks left running by a crashed/killed MinSync are
            # NOT successes. Mark them interrupted on startup.
            self._conn.execute(
                "UPDATE tasks SET status='failed', error_code='interrupted',"
                " error_message='MinSync restarted before task finished', finished_at=?"
                " WHERE status IN ('queued','running','cancelling')",
                (time.time(),),
            )
            self._conn.commit()

    # -- generic helpers -------------------------------------------------
    def _put(self, sql: str, params: tuple) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _get(self, sql: str, params: tuple) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # -- workspaces --------------------------------------------------------
    def add_workspace(self, wid: str, name: str, profile: str | None) -> None:
        self._put("INSERT INTO workspaces VALUES (?,?,?,?)", (wid, name, profile, time.time()))

    def get_workspace(self, wid: str) -> dict | None:
        return self._get("SELECT * FROM workspaces WHERE id=?", (wid,))

    def list_workspaces(self) -> list[dict]:
        return self._all("SELECT * FROM workspaces ORDER BY created_at")

    def delete_workspace(self, wid: str) -> None:
        self._put("DELETE FROM workspaces WHERE id=?", (wid,))

    # -- tasks -------------------------------------------------------------
    def add_task(self, t: dict) -> None:
        self._put(
            "INSERT INTO tasks(id,workspace_id,profile,kind,command_json,status,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (t["id"], t["workspace_id"], t.get("profile"), t.get("kind", "run"),
             json.dumps(t.get("command", {})), t["status"], t["created_at"]),
        )

    def update_task(self, task_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._put(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))

    def get_task(self, task_id: str) -> dict | None:
        return self._get("SELECT * FROM tasks WHERE id=?", (task_id,))

    def list_tasks(self, workspace_id: str | None = None, limit: int = 50) -> list[dict]:
        if workspace_id:
            return self._all(
                "SELECT * FROM tasks WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return self._all("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))

    def cleanup_old_tasks(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM tasks WHERE finished_at IS NOT NULL AND finished_at<?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    # -- artifacts -----------------------------------------------------------
    def add_artifact(self, a: dict) -> None:
        self._put(
            "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
            (a["id"], a.get("workspace_id"), a.get("task_id"), a["filename"],
             a["size"], a["sha256"], a["created_at"], a["path"]),
        )

    def get_artifact(self, aid: str) -> dict | None:
        return self._get("SELECT * FROM artifacts WHERE id=?", (aid,))

    def list_artifacts(self, workspace_id: str | None = None) -> list[dict]:
        if workspace_id:
            return self._all(
                "SELECT * FROM artifacts WHERE workspace_id=? ORDER BY created_at DESC",
                (workspace_id,))
        return self._all("SELECT * FROM artifacts ORDER BY created_at DESC")
