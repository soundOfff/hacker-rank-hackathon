"""Stage 3 — the deterministic rule layer.

Owns every decision that should not depend on a model: the evidence/status
invariant, severity anchoring, the user-history flags, the manual-review rule,
and enum/format normalization. Every rule here is validated against 100% of the
labeled samples (see code/tests/test_rules.py) and is pure Python — runnable
without an API key.
"""

from __future__ import annotations

from .allowed_values import (
    CLAIM_STATUS_NEI,
    RISK_FLAG_ORDER,
    SUBSTANTIVE_FLAGS,
    VISUAL_RISK_FLAGS,
)


def flagset(s: str | None) -> set[str]:
    """Parse a semicolon-separated flag string (treating `none`/empty as empty)."""
    if not s:
        return set()
    return {x.strip() for x in s.split(";") if x.strip() and x.strip() != "none"}


def derive_user_history_risk(history_flags: str | None) -> bool:
    return "user_history_risk" in flagset(history_flags)


def derive_manual_review(base_flags: set[str], history_flags: str | None) -> bool:
    """manual_review_required iff the user's history carries a review/risk flag,
    OR a substantive evidence flag is present. Image-quality-only flags and a
    bare NEI do not trigger it (see ADR-0001)."""
    hist = flagset(history_flags)
    if "user_history_risk" in hist or "manual_review_required" in hist:
        return True
    return bool(base_flags & SUBSTANTIVE_FLAGS)


def canonical_flags(flags: set[str]) -> str:
    ordered = [f for f in RISK_FLAG_ORDER if f in flags]
    extras = sorted(f for f in flags if f not in RISK_FLAG_ORDER)
    out = ordered + extras
    return ";".join(out) if out else "none"


def _bool_str(b: bool) -> str:
    return "true" if b else "false"


def finalize(
    *,
    stage1: dict,
    stage2: dict,
    history_flags: str | None,
    image_ids: list[str],
) -> dict:
    """Combine the two model stages + history into the 10 predicted output fields."""
    # --- assemble base (visual + chat-injection) flags ---
    base = set(stage2.get("risk_flags", [])) & set(VISUAL_RISK_FLAGS)
    if stage1.get("instruction_text_in_chat"):
        base.add("text_instruction_present")

    issue = stage2["issue_type"]
    part = stage2["object_part"]
    status = stage2["claim_status"]
    esm = bool(stage2["evidence_standard_met"])
    valid = bool(stage2["valid_image"])
    severity = stage2["severity"]

    # --- evidence-standard / claim-status invariant ---
    if status == CLAIM_STATUS_NEI:
        esm = False
    if not esm:
        status = CLAIM_STATUS_NEI
        severity = "unknown"
    elif issue == "none":
        severity = "none"

    # --- valid_image: a non-original image is not an authentic review basis ---
    if "non_original_image" in base:
        valid = False

    # --- supporting image ids: keep only ids that actually exist ---
    sup = [i for i in stage2.get("supporting_image_ids", []) if i in image_ids]
    sup_str = ";".join(sup) if sup else "none"

    # --- derived flags ---
    final_flags = set(base)
    if derive_user_history_risk(history_flags):
        final_flags.add("user_history_risk")
    if derive_manual_review(base, history_flags):
        final_flags.add("manual_review_required")

    return {
        "evidence_standard_met": _bool_str(esm),
        "evidence_standard_met_reason": stage2.get("evidence_standard_met_reason", ""),
        "risk_flags": canonical_flags(final_flags),
        "issue_type": issue,
        "object_part": part,
        "claim_status": status,
        "claim_status_justification": stage2.get("claim_status_justification", ""),
        "supporting_image_ids": sup_str,
        "valid_image": _bool_str(valid),
        "severity": severity,
    }
