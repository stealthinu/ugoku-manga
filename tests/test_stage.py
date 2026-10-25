"""Stage preparation on a synthetic page with the detectors and inpainter stubbed out (no model files needed)."""
import cv2
import numpy as np

from ugoku.pipeline import segment, stage


def make_page():
    img = np.full((400, 300, 3), 255, np.uint8)
    cv2.rectangle(img, (10, 10), (290, 390), (0, 0, 0), 3)
    cv2.ellipse(img, (150, 120), (80, 50), 0, 0, 360, (0, 0, 0), 3)  # balloon outline
    cv2.putText(img, "HI", (125, 135), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)  # "text"
    return img


def test_prepare_page(monkeypatch):
    img = make_page()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    txt = np.zeros(gray.shape, np.float32)
    txt[100:150, 120:190] = (gray[100:150, 120:190] < 128)
    monkeypatch.setattr(segment, "text_probability", lambda im: txt)
    monkeypatch.setattr(segment, "bubbles", lambda im, thr=0.4: [(0, [68.0, 68.0, 232.0, 172.0], 0.9)])
    monkeypatch.setattr(stage, "inpaint_page", lambda im, m, rects: np.where(m[..., None] > 0, 255, im).astype(np.uint8))
    pg = dict(
        page="t1",
        total_s=8,
        panels=[dict(id="t1-p1", rect=[0.03, 0.025, 0.94, 0.95], type="h3_full", action="A person nods.", magnitude="medium", mode="fl", timing_s=[0.0, 5.2], seed=7)],
        bubbles=[dict(id="b0", panel="t1-p1", rect=[0.23, 0.17, 0.54, 0.26], text="x", order=1, t_in=0.6, anim="pop")],
        fx=[],
    )
    entry, rep, specs, files = stage.prepare_page(img, pg, "w")
    assert [lay["kind"] for lay in entry["layers"]] == ["bubble"]
    base = files["pages/t1.png"]
    assert base[100:150, 120:190].min() > 200  # text removed from the base
    assert files["layers/t1-L0.png"].shape[2] == 4 and files["layers/t1-L0.png"][..., 3].max() == 255
    assert specs[0]["id"] == "t1-p1" and (specs[0]["src_rect"][2] - specs[0]["src_rect"][0]) % 2 == 0 and specs[0]["seed"] == 7
    assert files["stage/in/t1-p1.png"].shape[:2] == (specs[0]["src_rect"][3] - specs[0]["src_rect"][1], specs[0]["src_rect"][2] - specs[0]["src_rect"][0])
    assert not rep["warn"], rep


def _stubbed(monkeypatch, txt):
    monkeypatch.setattr(segment, "text_probability", lambda im: txt)
    monkeypatch.setattr(segment, "bubbles", lambda im, thr=0.4: [])
    monkeypatch.setattr(stage, "inpaint_page", lambda im, m, rects: np.where(m[..., None] > 0, 255, im).astype(np.uint8))


def _pg(bubbles):
    return dict(page="t2", total_s=8, panels=[dict(id="t2-p1", rect=[0.03, 0.025, 0.94, 0.95], type="h3_full", action="A.", magnitude="medium", mode="fl", timing_s=[0.0, 5.2], seed=1)],
                bubbles=bubbles, fx=[])


def test_leftover_text_on_light_ground_warns_but_art_does_not(monkeypatch):
    img = np.full((400, 300, 3), 255, np.uint8)
    cv2.putText(img, "HI", (125, 135), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
    img[200:260, 20:120] = 0  # dense dark art with a "text" blob inside it
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    txt = np.zeros(gray.shape, np.float32)
    txt[100:150, 120:190] = gray[100:150, 120:190] < 128
    _stubbed(monkeypatch, txt)
    _, rep, _, _ = stage.prepare_page(img, _pg([]), "w")
    assert any("leftover" in w for w in rep["warn"])
    img2 = np.full((400, 300, 3), 255, np.uint8)
    img2[200:260, 20:120] = 0
    txt2 = np.zeros(gray.shape, np.float32)
    txt2[210:250, 30:110] = 1
    _stubbed(monkeypatch, txt2)
    _, rep, _, _ = stage.prepare_page(img2, _pg([]), "w")
    assert not any("leftover" in w for w in rep["warn"]), rep


def test_empty_balloon_is_not_a_warning(monkeypatch):
    img = np.full((400, 300, 3), 255, np.uint8)
    _stubbed(monkeypatch, np.zeros((400, 300), np.float32))
    _, rep, _, _ = stage.prepare_page(img, _pg([dict(id="b0", panel="t2-p1", rect=[0.2, 0.2, 0.1, 0.1], text="", order=1, t_in=0.5, anim="pop")]), "w")
    assert not rep["warn"] and rep["baked"] == ["b:b0"]
