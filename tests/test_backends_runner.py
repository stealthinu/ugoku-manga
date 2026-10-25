import json

import pytest
from PIL import Image

from ugoku.backends.runner import RunnerError, make_runner
from ugoku.backends.video.base import PanelJob
from ugoku.backends.video.comfy_h3 import ComfyH3Backend


def _job(tmp_path, i="a"):
    p = tmp_path / f"{i}.png"
    Image.new("RGB", (60, 40), "white").save(p)
    return PanelJob(id=i, image=p, action="A man waves.", seed=3)


def test_pack_writes_spec_and_sums(tmp_path):
    be = ComfyH3Backend(runner={}, work_dir=tmp_path / "w")
    st = tmp_path / "stage"
    be.pack([_job(tmp_path)], st)
    spec = json.loads((st / "spec.json").read_text())
    assert spec["panels"][0]["seed"] == 3 and spec["frames"] == 124
    assert "in/a.png" in (st / "SHA256SUMS").read_text()
    assert (st / "comfy_h3_job.py").exists()


def test_external_runner_roundtrip_and_resume(tmp_path):
    """Fake 'queue': sync_in/command/status/sync_out are plain shell; a second run must not submit twice."""
    remote = tmp_path / "remote"
    counter = tmp_path / "count"
    cfg = dict(kind="external_command", poll_s=0, queue_id_regex=r"queued (q-\d+)", state_regex=r"state: (\w+)",
               sync_in="mkdir -p {remote_dir} && cp -r {stage_dir}/. {remote_dir}/",
               command=f"echo x >> {counter}; mkdir -p {{remote_dir}}/out; echo mp4 > {{remote_dir}}/out/a.mp4; "
                       "echo '{{\"items\": {{\"a\": {{\"status\": \"ok\"}}}}}}' > {remote_dir}/manifest.json; echo queued q-1",
               status="echo state: done", sync_out="mkdir -p {stage_dir}/result && cp -r {remote_dir}/. {stage_dir}/result/",
               remote_dir=str(remote / "{job_id}"))
    r = make_runner(cfg)
    stage = tmp_path / "stage"
    stage.mkdir()
    res = r.run(stage, "j1", 1, 60)
    assert (res / "manifest.json").exists() and (res / "out" / "a.mp4").exists()
    r.run(stage, "j1", 1, 60)
    assert counter.read_text().count("x") == 1


def test_external_runner_refuses_after_uncertain_submit(tmp_path):
    cfg = dict(kind="external_command", command="false", remote_dir=str(tmp_path / "r"))
    r = make_runner(cfg)
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(RunnerError):
        r.run(stage, "j", 1, 10)
    with pytest.raises(RunnerError, match="without a recorded id"):
        r.run(stage, "j", 1, 10)


def test_failed_job_still_returns_partial_manifest(tmp_path):
    cfg = dict(kind="external_command", poll_s=0, queue_id_regex=r"queued (q-\d+)", status="echo state: failed",
               command="mkdir -p {remote_dir}; echo '{{\"items\": {{}}}}' > {remote_dir}/manifest.json; echo queued q-2",
               sync_out="mkdir -p {stage_dir}/result && cp -r {remote_dir}/. {stage_dir}/result/", remote_dir=str(tmp_path / "r2"))
    stage = tmp_path / "s2"
    stage.mkdir()
    assert (make_runner(cfg).run(stage, "j2", 1, 10) / "manifest.json").exists()


def test_make_runner_unknown():
    with pytest.raises(RunnerError):
        make_runner({"kind": "nope"})


def test_minimax_requires_key_and_builds_body(tmp_path, monkeypatch):
    from ugoku.backends.video.minimax_api import MiniMaxBackend, MiniMaxError

    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    be = MiniMaxBackend()
    with pytest.raises(MiniMaxError):
        be.submit(_job(tmp_path))

    class R:
        def __init__(s, d): s.d = d
        def raise_for_status(s): pass
        def json(s): return s.d

    seen = {}

    class S:
        def post(s, url, json=None, **k):
            seen.update(url=url, body=json)
            return R({"task_id": "t1", "base_resp": {"status_code": 0}})

    monkeypatch.setenv("MINIMAX_API_KEY", "dummy")
    be = MiniMaxBackend(session=S())
    assert be.submit(_job(tmp_path)) == "t1"
    assert seen["body"]["model"] == "MiniMax-H3" and "last_frame_image" in seen["body"]
    assert "Picture 2" in seen["body"]["prompt"]  # first/last conditioning wording is kept
