"""Scoring against the labeled samples.

- Categorical fields: exact-match accuracy (claim_status is the headline).
- Set fields (risk_flags, supporting_image_ids): precision/recall/F1 over the
  semicolon set (`none`/empty == empty set).
- Free-text justification fields are not hard-scored (paraphrase-invariant);
  they are surfaced for spot-checking instead.
"""

from __future__ import annotations

CATEGORICAL_FIELDS = [
    "claim_status", "evidence_standard_met", "valid_image",
    "issue_type", "object_part", "severity",
]
SET_FIELDS = ["risk_flags", "supporting_image_ids"]
TEXT_FIELDS = ["evidence_standard_met_reason", "claim_status_justification"]


def _as_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {x.strip() for x in value.split(";") if x.strip() and x.strip() != "none"}


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def score(preds: list[dict], golds: list[dict]) -> dict:
    assert len(preds) == len(golds), "preds/golds length mismatch"
    n = len(preds)

    cat_correct = {f: 0 for f in CATEGORICAL_FIELDS}
    for p, g in zip(preds, golds):
        for f in CATEGORICAL_FIELDS:
            if (p.get(f, "") or "").strip() == (g.get(f, "") or "").strip():
                cat_correct[f] += 1
    cat_acc = {f: (cat_correct[f] / n if n else 0.0) for f in CATEGORICAL_FIELDS}
    macro_categorical = sum(cat_acc.values()) / len(cat_acc) if cat_acc else 0.0

    set_metrics = {}
    for f in SET_FIELDS:
        tp = fp = fn = 0
        per_row_f1 = []
        for p, g in zip(preds, golds):
            ps, gs = _as_set(p.get(f)), _as_set(g.get(f))
            rtp = len(ps & gs)
            rfp = len(ps - gs)
            rfn = len(gs - ps)
            tp += rtp
            fp += rfp
            fn += rfn
            per_row_f1.append(_prf(rtp, rfp, rfn)[2])
        pr, rc, f1 = _prf(tp, fp, fn)
        set_metrics[f] = {
            "precision": pr, "recall": rc, "micro_f1": f1,
            "mean_row_f1": sum(per_row_f1) / n if n else 0.0,
        }

    # exact full-row match across all 10 predicted fields (strict reference point)
    predicted_fields = CATEGORICAL_FIELDS + SET_FIELDS
    exact_rows = sum(
        1 for p, g in zip(preds, golds)
        if all((p.get(f, "") or "").strip() == (g.get(f, "") or "").strip() for f in predicted_fields)
    )

    return {
        "n": n,
        "claim_status_accuracy": cat_acc["claim_status"],
        "categorical_accuracy": cat_acc,
        "macro_categorical": macro_categorical,
        "set_fields": set_metrics,
        "exact_row_match": exact_rows / n if n else 0.0,
    }


def mismatches(preds: list[dict], golds: list[dict], field: str = "claim_status") -> list[dict]:
    out = []
    for p, g in zip(preds, golds):
        if (p.get(field, "") or "").strip() != (g.get(field, "") or "").strip():
            out.append({
                "user_id": g.get("user_id"),
                "image_paths": g.get("image_paths"),
                "pred": p.get(field),
                "gold": g.get(field),
            })
    return out
