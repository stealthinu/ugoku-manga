"""SQLite store and job queue (WAL mode, leases with heartbeat). One table of jobs; (project, page, stage) is unique, so enqueueing is idempotent."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, created REAL, reading TEXT, backend TEXT, direction TEXT, provider TEXT, model TEXT, state TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS pages(project TEXT, page TEXT, ord INTEGER, w INTEGER, h INTEGER, PRIMARY KEY(project, page));
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, page TEXT, stage TEXT, status TEXT, attempts INTEGER DEFAULT 0,
  payload TEXT, result TEXT, lease_until REAL, worker TEXT, pct REAL DEFAULT 0, msg TEXT DEFAULT '', created REAL, updated REAL, started REAL, UNIQUE(project, page, stage));
"""
CPU_STAGES = ("ingest", "direct", "prep", "compose")
GPU_STAGES = ("video",)
MAX_ATTEMPTS = 3


class DB:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._local = threading.local()
        with self.conn() as c:
            c.executescript(SCHEMA)

    def _c(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.c = c
        return c

    @contextmanager
    def conn(self):
        yield self._c()

    @contextmanager
    def tx(self):
        c = self._c()
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    # ---- projects / pages
    def add_project(self, pid: str, name: str, reading: str, backend: str, direction: str, provider: str = "", model: str = "") -> None:
        with self.tx() as c:
            c.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?)", (pid, name, time.time(), reading, backend, direction, provider, model, "queued", ""))

    def project(self, pid: str) -> dict | None:
        r = self._c().execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

    def projects(self) -> list[dict]:
        return [dict(r) for r in self._c().execute("SELECT * FROM projects ORDER BY created DESC")]

    def set_project(self, pid: str, **kw) -> None:
        with self.tx() as c:
            for k, v in kw.items():
                c.execute(f"UPDATE projects SET {k}=? WHERE id=?", (v, pid))

    def delete_project(self, pid: str) -> None:
        with self.tx() as c:
            for t in ("jobs", "pages"):
                c.execute(f"DELETE FROM {t} WHERE project=?", (pid,))
            c.execute("DELETE FROM projects WHERE id=?", (pid,))

    def add_pages(self, pid: str, pages: list[tuple[str, int, int]]) -> None:
        with self.tx() as c:
            for i, (name, w, h) in enumerate(pages):
                c.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?,?,?)", (pid, name, i, w, h))

    def pages(self, pid: str) -> list[dict]:
        return [dict(r) for r in self._c().execute("SELECT * FROM pages WHERE project=? ORDER BY ord", (pid,))]

    # ---- queue
    def enqueue(self, project: str, page: str, stage: str, payload: dict | None = None, force: bool = False) -> None:
        now = time.time()
        with self.tx() as c:
            r = c.execute("SELECT id, status FROM jobs WHERE project=? AND page=? AND stage=?", (project, page, stage)).fetchone()
            if r is None:
                c.execute("INSERT INTO jobs(project,page,stage,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)", (project, page, stage, "queued", json.dumps(payload or {}), now, now))
            elif force and r["status"] != "running":
                c.execute("UPDATE jobs SET status='queued', attempts=0, pct=0, msg='', result=NULL, lease_until=NULL, worker=NULL, updated=?, payload=? WHERE id=?",
                          (now, json.dumps(payload or {}), r["id"]))

    def drop(self, project: str, page: str, stage: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM jobs WHERE project=? AND page=? AND stage=? AND status!='running'", (project, page, stage))

    def claim(self, worker: str, stages: tuple[str, ...], lease_s: float = 60) -> dict | None:
        now = time.time()
        q = ",".join("?" * len(stages))
        with self.tx() as c:
            # a worker that died leaves a job 'running' with an expired lease: requeue it, or fail it after too many attempts
            c.execute("UPDATE jobs SET status='queued', worker=NULL WHERE status='running' AND lease_until<? AND attempts<?", (now, MAX_ATTEMPTS))
            c.execute("UPDATE jobs SET status='failed', msg='lease expired too often' WHERE status='running' AND lease_until<? AND attempts>=?", (now, MAX_ATTEMPTS))
            r = c.execute(f"SELECT * FROM jobs WHERE status='queued' AND stage IN ({q}) ORDER BY id LIMIT 1", stages).fetchone()
            if r is None:
                return None
            c.execute("UPDATE jobs SET status='running', attempts=attempts+1, worker=?, lease_until=?, started=?, updated=?, pct=0 WHERE id=?", (worker, now + lease_s, now, now, r["id"]))
            d = dict(r)
            d["attempts"] += 1
            d["worker"] = worker
            d["payload"] = json.loads(d["payload"] or "{}")
            return d

    def heartbeat(self, job_id: int, pct: float | None = None, msg: str | None = None, lease_s: float = 60) -> None:
        now = time.time()
        with self.tx() as c:
            c.execute("UPDATE jobs SET lease_until=?, updated=?, pct=COALESCE(?,pct), msg=COALESCE(?,msg) WHERE id=? AND status='running'", (now + lease_s, now, pct, msg, job_id))

    def finish(self, job_id: int, result: dict | None = None) -> None:
        with self.tx() as c:
            c.execute("UPDATE jobs SET status='done', pct=100, result=?, lease_until=NULL, updated=? WHERE id=?", (json.dumps(result or {}), time.time(), job_id))

    def fail(self, job_id: int, msg: str, retry: bool = False) -> None:
        with self.tx() as c:
            r = c.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            again = retry and r is not None and r["attempts"] < MAX_ATTEMPTS
            c.execute("UPDATE jobs SET status=?, msg=?, lease_until=NULL, updated=? WHERE id=?", ("queued" if again else "failed", msg[-500:], time.time(), job_id))

    def jobs(self, project: str) -> list[dict]:
        return [dict(r) for r in self._c().execute("SELECT * FROM jobs WHERE project=? ORDER BY id", (project,))]

    def job(self, project: str, page: str, stage: str) -> dict | None:
        r = self._c().execute("SELECT * FROM jobs WHERE project=? AND page=? AND stage=?", (project, page, stage)).fetchone()
        return dict(r) if r else None
