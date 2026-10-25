"""Golden checks on the sample works (needs the detector models; skipped otherwise)."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKS = sorted(p.parent.name for p in (ROOT / "samples").glob("*/truth.json"))


def _models() -> bool:
    try:
        from ugoku.models import model_path

        model_path("ctd")
        model_path("bubble")
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _models(), reason="detector models not installed")
@pytest.mark.parametrize("work", WORKS)
def test_detectors_vs_truth(work):
    from eval.golden import evaluate_work

    r = evaluate_work(ROOT / "samples" / work)
    assert r["panel_mean_iou"] >= 0.95  # classical detector only, no LLM correction
    assert r["unit_recall"]["bubble"] >= 0.95
    assert r["unit_recall"]["sfx"] >= 0.95
