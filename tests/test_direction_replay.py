"""Replay-based CI test of the direction workflow: recorded LLM answers, a synthetic page, no network, no models."""
import json
from pathlib import Path

import cv2
import numpy as np

from ugoku.backends.llm import make_provider
from ugoku.pipeline.direction.validate import errors
from ugoku.pipeline.direction.workflow import assemble, direct_page, validate_ctx, wrap_direction
from ugoku.pipeline.units import DS, Unit, UnitSet

FIX = Path(__file__).parent / "fixtures" / "replay"
W, H = 800, 1200


def synthetic_page():
    img = np.full((H, W, 3), 255, np.uint8)
    for x0, y0, x1, y1 in [(416, 36, 776, 576), (24, 36, 384, 576), (24, 624, 776, 1164)]:
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), 6)
        cv2.circle(img, ((x0 + x1) // 2, (y0 + y1) // 2), 60, (90, 90, 90), -1)  # some art
    return img


def synthetic_units():
    def mk(uid, kind, box):
        m = np.zeros((H // DS, W // DS), bool)
        x0, y0, x1, y1 = (box[0] * W / DS, box[1] * H / DS, box[2] * W / DS, box[3] * H / DS)
        m[int(y0) : int(y1), int(x0) : int(x1)] = True
        return Unit(uid, kind, box, m, m)

    return UnitSet([mk("U1", "balloon", [0.70, 0.08, 0.90, 0.16]), mk("U2", "balloon", [0.56, 0.20, 0.76, 0.28]), mk("U3", "sfx", [0.10, 0.10, 0.28, 0.22])], W, H)


def test_workflow_replay(tmp_path):
    prov = make_provider("replay", recording=FIX)
    pg, rep = direct_page(synthetic_page(), "syn", prov, tmp_path, "rtl", synthetic_units())
    assert rep["valid"] and rep["valid_without_degrade"], rep["issues"]
    assert rep["critic_rounds"] == 2 and rep["redirect"]  # 1 of 3 panels patched (> 30%): directing ran again
    types = {p["id"]: p["type"] for p in pg["panels"]}
    assert types == {"syn-p1": "h3_full", "syn-p2": "h3_full", "syn-p3": "static"}
    p2 = next(p for p in pg["panels"] if p["id"] == "syn-p2")
    assert p2["mode"] == "f"  # the critic's patch was applied
    assert [b["order"] for b in pg["bubbles"]] == [1, 2]
    assert pg["bubbles"][1]["anim"] == "shake"
    assert pg["bubbles"][0]["t_in"] < pg["bubbles"][1]["t_in"]
    assert 7 <= pg["total_s"] <= 12
    assert pg["fx"][0]["preset"] == "impact" and pg["fx"][0]["kind"] == "sfx"
    d = wrap_direction([pg], "syn", "rtl", prov)
    assert d["format"] == "ugoku-direction/1"
    json.dumps(d)


def test_order_constraint_from_llm(tmp_path):
    prov = make_provider("replay", recording=FIX)
    from ugoku.pipeline.direction.workflow import apply_observation, init_ctx

    ctx = init_ctx(synthetic_page(), "syn", "rtl", synthetic_units())
    apply_observation(ctx, prov.complete("", tag="observe:syn"))
    direct = prov.complete("", tag="direct:syn")
    pg = assemble(ctx, direct, {"P1": ["U2", "U1"]})  # the order check puts U2 first
    assert [b["unit"] for b in pg["bubbles"]] == ["U2", "U1"]
    assert not errors(validate_ctx(ctx, pg))
