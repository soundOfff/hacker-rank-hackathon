#!/usr/bin/env python3
"""Validate the deterministic rule layer against 100% of the labeled samples.

Runs with NO API key — it only exercises pure-Python logic in orchestrate.rules
against dataset/sample_claims.csv. Run directly (`python code/tests/test_rules.py`)
or under pytest.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # code/

from orchestrate import datasets, rules
from orchestrate.config import DATASET_DIR

DERIVED = {"user_history_risk", "manual_review_required"}


def _rows():
    golds = datasets.load_claims(DATASET_DIR / "sample_claims.csv")
    history = datasets.load_user_history(DATASET_DIR / "user_history.csv")
    return golds, history


def check_all() -> list[str]:
    golds, history = _rows()
    failures: list[str] = []

    for row in golds:
        uid = row["user_id"]
        gold_flags = rules.flagset(row["risk_flags"])
        base = gold_flags - DERIVED
        hist_flags = history.get(uid, {}).get("history_flags", "none")
        esm = row["evidence_standard_met"] == "true"
        nei = row["claim_status"] == "not_enough_information"

        def fail(msg):
            failures.append(f"{uid} ({row['image_paths'].split(';')[0]}): {msg}")

        # 1. user_history_risk derivation
        if rules.derive_user_history_risk(hist_flags) != ("user_history_risk" in gold_flags):
            fail("user_history_risk derivation mismatch")

        # 2. manual_review_required derivation
        if rules.derive_manual_review(base, hist_flags) != ("manual_review_required" in gold_flags):
            fail("manual_review_required derivation mismatch")

        # 3. evidence/status invariant holds in ground truth
        if esm == nei:
            fail(f"invariant violated in gold: esm={esm} nei={nei}")

        # 4. severity anchoring holds in ground truth
        if not esm and row["severity"] != "unknown":
            fail(f"esm=false but severity={row['severity']} (expected unknown)")
        if row["issue_type"] == "none" and row["severity"] != "none":
            fail(f"issue_type=none but severity={row['severity']} (expected none)")

        # 5. canonical ordering reproduces the gold flag string
        if rules.canonical_flags(gold_flags) != (row["risk_flags"] or "none"):
            fail(f"canonical_flags={rules.canonical_flags(gold_flags)!r} != gold {row['risk_flags']!r}")

        # 6. end-to-end finalize() reproduces the labeled output, given the
        #    correct *visual* inputs (i.e. the rule layer adds no error of its own)
        image_ids = [datasets.image_id(p) for p in datasets.parse_image_paths(row["image_paths"])]
        stage2 = {
            "issue_type": row["issue_type"],
            "object_part": row["object_part"],
            "claim_status": row["claim_status"],
            "evidence_standard_met": esm,
            "valid_image": row["valid_image"] == "true",
            "severity": row["severity"],
            "supporting_image_ids": (
                [] if row["supporting_image_ids"] == "none"
                else row["supporting_image_ids"].split(";")
            ),
            "risk_flags": sorted(base),  # visual flags only (image text included)
            "evidence_standard_met_reason": row["evidence_standard_met_reason"],
            "claim_status_justification": row["claim_status_justification"],
            "confidence": "high",
        }
        stage1 = {"instruction_text_in_chat": False}
        out = rules.finalize(stage1=stage1, stage2=stage2, history_flags=hist_flags, image_ids=image_ids)
        for field in ["claim_status", "evidence_standard_met", "valid_image", "severity",
                      "issue_type", "object_part", "risk_flags", "supporting_image_ids"]:
            if out[field] != (row[field] or ("none" if field == "risk_flags" else "")):
                fail(f"finalize {field}={out[field]!r} != gold {row[field]!r}")

    return failures


def test_rule_layer_matches_samples():
    failures = check_all()
    assert not failures, "Rule-layer mismatches:\n" + "\n".join(failures)


if __name__ == "__main__":
    golds, _ = _rows()
    failures = check_all()
    if failures:
        print(f"FAIL: {len(failures)} mismatch(es) across {len(golds)} samples:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print(f"PASS: rule layer reproduces all deterministic fields on {len(golds)}/{len(golds)} samples.")
