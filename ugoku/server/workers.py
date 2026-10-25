"""Worker loops: a CPU pool (N threads) and a GPU pool (1 thread) claim jobs from the SQLite queue; a heartbeat keeps the lease alive while a job runs."""
from __future__ import annotations

import threading
import time
import traceback

from .db import CPU_STAGES, GPU_STAGES
from .stages import EXEC, StageError, Store, advance, project_state

LEASE_S = 45


def run_one(store: Store, worker: str, stages: tuple[str, ...]) -> bool:
    job = store.db.claim(worker, stages, LEASE_S)
    if job is None:
        return False
    stop = threading.Event()

    def beat():
        while not stop.wait(LEASE_S / 3):
            store.db.heartbeat(job["id"], lease_s=LEASE_S)

    th = threading.Thread(target=beat, daemon=True)
    th.start()

    def progress(pct: float, msg: str = ""):
        store.db.heartbeat(job["id"], pct, msg, LEASE_S)

    try:
        if job["stage"] == "ingest":
            store.db.set_project(job["project"], state="running", error="")
        res = EXEC[job["stage"]](store, job, progress)
        stop.set()
        store.db.finish(job["id"], res)
        advance(store, job["project"])
        store.db.set_project(job["project"], state=project_state(store, job["project"]))
    except StageError as e:
        stop.set()
        store.db.fail(job["id"], str(e), retry=e.retry)
        store.db.set_project(job["project"], state="failed", error=f"{job['stage']} {job['page']}: {e}")
    except Exception as e:  # noqa: BLE001
        stop.set()
        tb = traceback.format_exc()
        store.db.fail(job["id"], f"{type(e).__name__}: {e}", retry=True)
        j = store.db.job(job["project"], job["page"], job["stage"])
        if j and j["status"] == "failed":
            store.db.set_project(job["project"], state="failed", error=f"{job['stage']} {job['page']}: {type(e).__name__}: {e}\n{tb[-600:]}")
    return True


class Pool:
    def __init__(self, store: Store, cpu: int = 2, gpu: int = 1, idle_s: float = 0.5):
        self.store, self.idle_s = store, idle_s
        self._stop = threading.Event()
        self.threads = [threading.Thread(target=self._loop, args=(f"cpu{i}", CPU_STAGES), daemon=True) for i in range(cpu)]
        self.threads += [threading.Thread(target=self._loop, args=(f"gpu{i}", GPU_STAGES), daemon=True) for i in range(gpu)]

    def _loop(self, name: str, stages):
        while not self._stop.is_set():
            try:
                if not run_one(self.store, name, stages):
                    time.sleep(self.idle_s)
            except Exception:  # noqa: BLE001 - never let a worker thread die
                traceback.print_exc()
                time.sleep(2)

    def start(self):
        for t in self.threads:
            t.start()

    def stop(self):
        self._stop.set()
