import numpy as np


def test_inpaint_falls_back_to_opencv_without_model(tmp_path, monkeypatch):
    monkeypatch.setenv("UGOKU_MODEL_DIR", str(tmp_path))
    from ugoku.pipeline import inpaint as ip

    monkeypatch.setattr(ip, "_lama", None)
    img = np.full((100, 100, 3), 230, np.uint8)
    img[40:50, 40:60] = 0
    m = np.zeros((100, 100), np.uint8)
    m[38:52, 38:62] = 1
    out = ip.inpaint(img, m)
    assert int(out[45, 50].mean()) > 200
