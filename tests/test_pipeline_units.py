import json
import shutil

import numpy as np
import pytest

from ugoku.pipeline import compose
from ugoku.pipeline.direction.io import load_direction
from ugoku.pipeline.segment import cut_dark_components, match_by_rect, overlap
from ugoku.pipeline.stage import px_rect, stage_rect


def test_rects():
    assert px_rect([0.1, 0.2, 0.5, 0.5], 100, 200) == [10, 40, 60, 140]
    r = stage_rect({"rect": [0.0, 0.0, 0.333, 0.333]}, 101, 101)
    assert (r[2] - r[0]) % 2 == 0 and (r[3] - r[1]) % 2 == 0


def test_overlap_and_match():
    assert overlap([0, 0, 10, 10], [5, 0, 15, 10]) == 0.5
    units = [dict(kind="balloon", box=[0, 0, 10, 10]), dict(kind="balloon", box=[50, 50, 60, 60])]
    res, free = match_by_rect(units, [[1, 1, 11, 11]])
    assert res == {0: [0]} and free == [1]


def test_cut_dark_components_fills_hollow():
    g = np.full((60, 60), 255, np.uint8)
    g[20:40, 20:40] = 0
    g[25:35, 25:35] = 255  # hollow
    m = cut_dark_components(g, [18, 18, 42, 42], pad=6)
    assert m[30, 30] == 1 and m[5, 5] == 0


def test_direction_format(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"format": "other", "pages": []}))
    with pytest.raises(ValueError):
        load_direction(p)


def test_retime():
    pages = [dict(total_s=10.0, panels=[dict(start=2.0)], layers=[dict(t_in=1.0)], overlays=[])]
    compose.retime(pages, 0.7)
    assert pages[0]["total_s"] == 7.0 and pages[0]["panels"][0]["start"] == 1.4 and pages[0]["layers"][0]["t_in"] == 0.7


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_dummy_backend(tmp_path):
    import cv2

    from ugoku.backends.video.base import PanelJob
    from ugoku.backends.video.dummy import DummyBackend

    img = tmp_path / "p.png"
    cv2.imwrite(str(img), np.random.default_rng(0).integers(0, 255, (64, 48, 3), dtype=np.uint8))
    out = DummyBackend().generate(PanelJob(id="a", image=img, action="x", frames=6), tmp_path / "a.mp4")
    assert out.exists() and (tmp_path / "a.webm").exists()
    cap = cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 6 and int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 48
