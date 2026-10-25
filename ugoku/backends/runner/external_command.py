"""Generic template-based runner for a GPU that lives elsewhere (another host, a job queue).

The user supplies shell command templates; this module knows nothing about any particular queue.

  sync_in    copy the stage directory to where the job will run
  command    submit/run the job; its stdout is searched with `queue_id_regex` for a queue id (optional)
  status     (optional) print the queue state for {queue_id}; matched with `state_regex`
  sync_out   copy the result directory back into {stage_dir}/result

Template variables: {stage_dir} {remote_dir} {job_id} {n_panels} {expect_s} {python} {queue_id}, plus every key of the `vars` table.
Values in `vars` may themselves use the built-in variables. A submission record is written to the stage directory before and after
submitting, so a re-run after a crash resumes polling instead of submitting twice; if a submission was attempted but no id was recorded
the runner refuses to continue (inspect the queue by hand).
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from .base import RunnerError


class ExternalCommandRunner:
    name = "external_command"

    def __init__(self, command: str, sync_in: str = "", sync_out: str = "", status: str = "", queue_id_regex: str = "", state_regex: str = "state: (\\w+)",
                 done_states: list[str] | None = None, failed_states: list[str] | None = None, poll_s: float = 60, remote_dir: str = "ugoku/{job_id}",
                 python: str = "python3", vars: dict | None = None, timeout_factor: float = 1.5, sleep=time.sleep):
        self.command, self.sync_in, self.sync_out, self.status = command, sync_in, sync_out, status
        self.queue_id_re = re.compile(queue_id_regex) if queue_id_regex else None
        self.state_re = re.compile(state_regex)
        self.done = set(done_states or ["done"])
        self.failed = set(failed_states or ["failed", "cancelled", "canceled", "timeout", "interrupted"])
        self.poll_s, self.remote_dir, self.python, self.vars = poll_s, remote_dir, python, dict(vars or {})
        self.timeout_factor, self.sleep = timeout_factor, sleep

    # -- helpers
    def _vars(self, stage_dir: Path, job_id: str, n_panels: int, expect_s: float, queue_id: str = "") -> dict:
        v = dict(stage_dir=str(stage_dir), job_id=job_id, n_panels=n_panels, expect_s=int(expect_s), python=self.python, queue_id=queue_id)
        v["remote_dir"] = self.remote_dir.format(**v)
        for k, t in self.vars.items():
            v[k] = str(t).format(**v)
        return v

    def _sh(self, tmpl: str, v: dict, what: str, check: bool = True) -> str:
        cmd = tmpl.format(**v)
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        if check and r.returncode != 0:
            raise RunnerError(f"{what} failed rc={r.returncode}: {out[-400:]}")
        return out

    # -- main
    def run(self, stage_dir: Path, job_id: str, n_panels: int, expect_s: float) -> Path:
        stage_dir = Path(stage_dir)
        rec_path = stage_dir / "submission.json"
        rec = json.loads(rec_path.read_text()) if rec_path.exists() else {}
        v = self._vars(stage_dir, job_id, n_panels, expect_s, rec.get("queue_id", ""))
        if rec.get("status") == "attempting":
            raise RunnerError(f"a submission of {job_id} was attempted without a recorded id; inspect the queue, then delete {rec_path}")
        if not rec.get("queue_id") and rec.get("status") != "submitted":
            if self.sync_in:
                self._sh(self.sync_in, v, "sync_in")
            rec_path.write_text(json.dumps(dict(status="attempting", time=time.strftime("%Y-%m-%dT%H:%M:%S%z"))))
            try:
                out = self._sh(self.command, v, "command")
            except RunnerError:
                rec_path.write_text(json.dumps(dict(status="attempting", note="command failed or uncertain")))
                raise
            qid = ""
            if self.queue_id_re:
                m = self.queue_id_re.search(out)
                if not m:
                    raise RunnerError(f"no queue id in the command output: {out[-300:]}")
                qid = m.group(1)
            rec = dict(status="submitted", queue_id=qid, output=out[-500:])
            rec_path.write_text(json.dumps(rec))
            v["queue_id"] = qid
        failure = ""
        if self.status and v["queue_id"]:
            try:
                self._wait(v, expect_s)
            except RunnerError as e:
                failure = str(e)  # a job that ended "failed" may still have written a manifest naming the panels that did succeed
        res = stage_dir / "result"
        if self.sync_out:
            try:
                self._sh(self.sync_out, v, "sync_out")
            except RunnerError:
                if not failure:
                    raise
        if not (res / "manifest.json").exists():
            raise RunnerError(failure or f"no manifest.json in {res} after sync_out")
        return res

    def _wait(self, v: dict, expect_s: float) -> None:
        t0 = time.time()
        limit = max(expect_s * self.timeout_factor, 600)
        state = ""
        while True:
            out = self._sh(self.status, v, "status", check=False)
            m = self.state_re.search(out)
            state = m.group(1) if m else state
            if state in self.done:
                return
            if state in self.failed:
                raise RunnerError(f"queue job {v['queue_id']} ended in state {state}")
            if time.time() - t0 > limit + 4 * 3600:  # queue time is not part of expect_s; this only stops a stuck poll loop
                raise RunnerError(f"gave up waiting for {v['queue_id']} (last state {state or 'unknown'})")
            self.sleep(self.poll_s)
