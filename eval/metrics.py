"""Evaluation metrics: matching, panel/unit/order scores. Pure functions, no data access."""
from __future__ import annotations

import numpy as np


def iou_rect(a, b) -> float:
    """IoU of two [x, y, w, h] rects."""
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax1, bx1) - max(a[0], b[0]))
    ih = max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    u = a[2] * a[3] + b[2] * b[3] - inter
    return inter / u if u > 0 else 0.0


def hungarian(cost: np.ndarray) -> list[tuple[int, int]]:
    """Minimum-cost assignment (scipy if present, otherwise a greedy fallback on the same matrix)."""
    if cost.size == 0:
        return []
    try:
        from scipy.optimize import linear_sum_assignment

        r, c = linear_sum_assignment(cost)
        return list(zip(r.tolist(), c.tolist()))
    except ImportError:
        pairs, used_r, used_c = [], set(), set()
        for flat in np.argsort(cost, axis=None):
            r, c = divmod(int(flat), cost.shape[1])
            if r not in used_r and c not in used_c:
                pairs.append((r, c))
                used_r.add(r)
                used_c.add(c)
        return pairs


def match_rects(pred: list, ref: list, thr: float = 0.5) -> list[tuple[int, int, float]]:
    """Optimal one-to-one matching on IoU; returns (pred_idx, ref_idx, iou) for pairs with IoU >= thr."""
    if not pred or not ref:
        return []
    M = np.array([[iou_rect(p, r) for r in ref] for p in pred])
    return [(i, j, float(M[i, j])) for i, j in hungarian(-M) if M[i, j] >= thr]


def prf(n_match: int, n_pred: int, n_ref: int) -> tuple[float, float]:
    """(recall, precision)"""
    return (n_match / n_ref if n_ref else 1.0, n_match / n_pred if n_pred else 1.0)


def kendall_tau(a: list, b: list) -> float:
    """Kendall tau between two rankings of the same items (given as rank lists); 1.0 for fewer than 2 items."""
    n = len(a)
    if n < 2:
        return 1.0
    c = d = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            c += s > 0
            d += s < 0
    return (c - d) / (c + d) if c + d else 1.0


def cohen_kappa(a: list, b: list) -> float:
    if not a:
        return 1.0
    labels = sorted(set(a) | set(b))
    po = np.mean([x == y for x, y in zip(a, b)])
    pe = sum((a.count(l) / len(a)) * (b.count(l) / len(b)) for l in labels)
    return 1.0 if pe >= 1 else float((po - pe) / (1 - pe))


def panel_scores(pred: list, ref: list) -> dict:
    """pred/ref: lists of [x, y, w, h]. Mean IoU of matched (IoU>=0.5) panels, recall and precision at 0.5."""
    m = match_rects(pred, ref, 0.5)
    r, p = prf(len(m), len(pred), len(ref))
    return dict(n_pred=len(pred), n_ref=len(ref), matched=len(m), mean_iou=float(np.mean([x[2] for x in m])) if m else 0.0, recall=r, precision=p)


def box_overlap(a, b) -> float:
    """Intersection over the smaller area of two [x0, y0, x1, y1] boxes."""
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    s = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return iw * ih / s if s > 0 else 0.0
