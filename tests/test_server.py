import time
import zipfile

import cv2
import numpy as np
import pytest

from ugoku.server.db import DB
from ugoku.server.stages import StageError, check_page, natural_key, read_pages


def test_queue_idempotent_and_lease(tmp_path):
    db = DB(tmp_path / "q.sqlite")
    db.add_project("p", "n", "rtl", "dummy", "heuristic")
    db.enqueue("p", "", "ingest")
    db.enqueue("p", "", "ingest")
    assert len(db.jobs("p")) == 1
    j = db.claim("w1", ("ingest",), lease_s=0.05)
    assert j and j["attempts"] == 1
    time.sleep(0.1)
    again = db.claim("w2", ("ingest",), lease_s=30)  # the first worker died: its expired lease is requeued
    assert again and again["id"] == j["id"] and again["attempts"] == 2 and again["worker"] == "w2"
    db.heartbeat(again["id"], 40, "half")
    assert db.job("p", "", "ingest")["pct"] == 40
    db.finish(again["id"], {"ok": 1})
    assert db.job("p", "", "ingest")["status"] == "done"
    db.enqueue("p", "", "ingest", force=True)  # a rerun after an edit
    assert db.job("p", "", "ingest")["status"] == "queued"


def test_lease_expiry_gives_up(tmp_path):
    db = DB(tmp_path / "q.sqlite")
    db.add_project("p", "n", "rtl", "dummy", "heuristic")
    db.enqueue("p", "", "video")
    for _ in range(3):
        assert db.claim("w", ("video",), lease_s=0.01)
        time.sleep(0.03)
    assert db.claim("w", ("video",), lease_s=1) is None
    assert db.job("p", "", "video")["status"] == "failed"


def test_stage_pools_are_separate(tmp_path):
    db = DB(tmp_path / "q.sqlite")
    db.add_project("p", "n", "rtl", "dummy", "heuristic")
    db.enqueue("p", "", "video")
    assert db.claim("cpu", ("ingest", "direct", "prep", "compose")) is None
    assert db.claim("gpu", ("video",))


def _png(w=40, h=30, v=200):
    ok, b = cv2.imencode(".png", np.full((h, w, 3), v, np.uint8))
    return b.tobytes()


def test_read_pages_zip_natural_order_and_unsafe_names(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        for n in ("p10.png", "p2.png", "p1.png", "../evil.png", "__MACOSX/x.png", "notes.txt"):
            f.writestr(n, _png() if n.endswith(".png") else b"hi")
    pages = read_pages(z)
    assert [n for n, _ in pages] == ["p1", "p2", "p10"]
    with zipfile.ZipFile(tmp_path / "b.zip", "w") as f:
        f.writestr("x.txt", b"hi")
    with pytest.raises(StageError):
        read_pages(tmp_path / "b.zip")
    assert sorted(["a10", "a9", "a1"], key=natural_key) == ["a1", "a9", "a10"]


def test_check_page_rules():
    ok = dict(panels=[dict(id="a", rect=[0.1, 0.1, 0.5, 0.5], type="h3_full", action="x", mode="fl", magnitude="medium")], bubbles=[dict(id="b", panel="a")])
    assert check_page(ok) == []
    bad = dict(panels=[dict(id="a", rect=[0.8, 0.1, 0.5, 0.5], type="h3_full", action="", mode="zz", magnitude="medium")], bubbles=[dict(id="b", panel="q")])
    assert len(check_page(bad)) == 4


@pytest.fixture
def client(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ugoku.server.app import create_app

    return TestClient(create_app(tmp_path / "data", start_workers=False))


def test_app_upload_rules_and_files(client):
    r = client.post("/api/projects", files={"file": ("a.png", _png(), "image/png")}, data={"reading": "rtl"})
    assert r.status_code == 400  # no rights confirmation
    r = client.post("/api/projects", files={"file": ("a.exe", b"x")}, data={"rights": "true"})
    assert r.status_code == 400
    r = client.post("/api/projects", files={"file": ("a.png", _png(), "image/png")}, data={"rights": "true", "backend": "nope"})
    assert r.status_code == 400
    r = client.post("/api/projects", files={"file": ("a.png", _png(), "image/png")}, data={"rights": "true"})
    pid = r.json()["id"]
    s = client.get(f"/api/projects/{pid}").json()
    assert s["state"] == "running" or s["state"] == "queued"
    assert client.get(f"/api/projects/{pid}/export/gallery.zip").status_code == 409
    assert client.get(f"/p/{pid}/../../etc/passwd").status_code in (404, 400)
    assert client.get(f"/p/{pid}/work/x").status_code == 404
    assert client.get("/p/nope/out/x").status_code == 404
    assert "ugoku" in client.get("/").text and client.get("/ui/app.js").status_code == 200
    assert client.delete(f"/api/projects/{pid}").status_code == 200


def test_serve_refuses_public_bind_without_flag(capsys):
    from ugoku.cli import main

    pytest.importorskip("uvicorn")
    assert main(["serve", "--host", "0.0.0.0", "--data", "x"]) == 2
