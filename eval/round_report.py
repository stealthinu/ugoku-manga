"""Write `eval/rounds/<tag>.md` (numbers only) from a direction_eval metrics file, with the plan's gate thresholds."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .common import load_eval

# (key, label, threshold, direction) from the plan's quality bar (CPU / LLM-only gates)
GATES = [
    ("panel_mean_iou", "panel mean IoU", 0.85, ">="),
    ("panel_recall", "panel recall (IoU>=0.5)", 0.95, ">="),
    ("panel_precision", "panel precision", 0.90, ">="),
    ("bubble_recall", "bubble recall", 0.90, ">="),
    ("sfx_manpu_recall", "SFX+manpu recall", 0.75, ">="),
    ("unit_tau_mean", "order tau (bubbles)", 0.90, ">="),
    ("unit_page_exact", "order page exact", 0.80, ">="),
    ("panel_page_exact", "panel sequence page exact", 0.80, ">="),
    ("h3_agree", "h3 selection agreement", 0.80, ">="),
    ("schema_valid_no_degrade", "schema valid without degrade (pages)", 0.95, ">="),
]


def main(argv=None) -> int:
    args = argv or sys.argv[1:]
    tag = args[0]
    note = args[1] if len(args) > 1 else ""
    cfg = load_eval()
    m = json.load(open(Path(cfg["out"]) / tag / "metrics.json"))["summary"]
    lines = [f"# Round {tag}", "", note, "", "| gate | value | target | ok |", "|---|---|---|---|"]
    for k, label, thr, _ in GATES:
        v = m.get(k)
        lines.append(f"| {label} | {v:.3f} | >= {thr} | {'yes' if v is not None and v >= thr else 'NO'} |" if v is not None else f"| {label} | n/a | >= {thr} | |")
    lines += ["", "Other numbers:", "", "```", json.dumps({k: v for k, v in m.items() if k not in {g[0] for g in GATES}}, indent=1), "```", ""]
    out = Path(__file__).parent / "rounds" / f"{tag}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
