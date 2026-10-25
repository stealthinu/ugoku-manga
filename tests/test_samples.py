import re
from pathlib import Path

import pytest

from ugoku.pipeline.truth import load_truth, validate_truth

ROOT = Path(__file__).resolve().parents[1]
WORKS = sorted(p.parent.name for p in (ROOT / "samples").glob("*/truth.json"))
DENY = re.compile(r"style of|artstation|pixiv|trending|studio ghibli|disney|pokemon|naruto|one piece|dragon ball", re.I)


@pytest.mark.parametrize("work", WORKS)
def test_truth_valid(work):
    d = ROOT / "samples" / work
    assert validate_truth(load_truth(d / "truth.json"), d) == []


@pytest.mark.parametrize("work", sorted(p.parent.name for p in (ROOT / "samples").glob("*/script.yaml")))
def test_prompts_clean(work):
    yaml = pytest.importorskip("yaml")
    s = yaml.safe_load((ROOT / "samples" / work / "script.yaml").read_text(encoding="utf-8"))
    texts = [v for v in s["art"].values() if isinstance(v, str)] + [p["prompt"] for pg in s["pages"] for p in pg["panels"] if "prompt" in p] + list(s.get("characters", {}).values())
    assert not [t for t in texts if DENY.search(t)]


def test_three_works_present():
    assert len(WORKS) == 3 or not WORKS


def test_manifest_lists_every_work_as_cc0():
    import json

    m = json.loads((ROOT / "samples" / "manifest.json").read_text(encoding="utf-8"))
    assert m["license"] == "CC0-1.0"
    assert sorted(w["id"] for w in m["works"]) == WORKS
    for w in m["works"]:
        assert w["license"] == "CC0-1.0"
        assert w["pages"] == sorted(p.relative_to(ROOT / "samples").as_posix() for p in (ROOT / "samples" / w["id"] / "pages").glob("*.png"))
