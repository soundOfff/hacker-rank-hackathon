#!/usr/bin/env python3
"""The vector store feeds deterministic visual flags into the rule layer
(ADR-0004). This locks in that contract with no DB / no API key: a
`non_original_image` flag from the reused-image detector must flow through the
same invariants as a model-emitted one.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # code/

from orchestrate import rules

_STAGE1 = {"instruction_text_in_chat": False}
_STAGE2 = {
    "issue_type": "dent",
    "object_part": "door",
    "claim_status": "supported",
    "evidence_standard_met": True,
    "valid_image": True,
    "severity": "low",
    "supporting_image_ids": ["img_1"],
    "risk_flags": [],
    "evidence_standard_met_reason": "clear",
    "claim_status_justification": "visible dent",
    "confidence": "high",
}


def _finalize(extra):
    return rules.finalize(
        stage1=dict(_STAGE1), stage2=dict(_STAGE2),
        history_flags="none", image_ids=["img_1"], extra_visual_flags=extra,
    )


def check_all() -> list[str]:
    failures: list[str] = []

    # Baseline: no extra flags -> clean supported row, valid image.
    base = _finalize(set())
    if base["valid_image"] != "true" or "non_original_image" in base["risk_flags"]:
        failures.append(f"baseline unexpectedly flagged: {base['risk_flags']} / {base['valid_image']}")

    # Reused-image flag -> non_original_image present, valid_image forced false,
    # manual_review_required derived (it's a substantive flag).
    reused = _finalize({"non_original_image"})
    if "non_original_image" not in reused["risk_flags"]:
        failures.append("non_original_image not propagated from extra_visual_flags")
    if reused["valid_image"] != "false":
        failures.append(f"valid_image should be false on non_original_image, got {reused['valid_image']}")
    if "manual_review_required" not in reused["risk_flags"]:
        failures.append("manual_review_required not derived for non_original_image")

    # Unknown / non-visual flags from the store are ignored (enum safety).
    bogus = _finalize({"fraud_ring", "definitely_fake"})
    extra_in_output = rules.flagset(bogus["risk_flags"]) - rules.flagset(base["risk_flags"])
    if extra_in_output:
        failures.append(f"bogus extra flags leaked into output: {extra_in_output}")

    return failures


def test_extra_visual_flags():
    failures = check_all()
    assert not failures, "extra_visual_flags contract failures:\n" + "\n".join(failures)


if __name__ == "__main__":
    failures = check_all()
    if failures:
        print(f"FAIL: {len(failures)} contract mismatch(es):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("PASS: extra_visual_flags flow through the rule-layer invariants.")
