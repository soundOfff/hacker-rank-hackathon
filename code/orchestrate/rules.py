"""Stage 3 — Deterministic Rule Layer (pure Python, no API calls).

The rule layer enforces invariants that models should not decide, consolidates flags
from all sources, and normalizes the final output. Every rule is validated against
100% of the 20 labeled samples (code/tests/test_rules.py) and runs with no API key.

Responsibilities:

1. **Evidence → Status coupling**: If the evidence standard isn't met, the claim
   status must be not_enough_information and severity must be unknown. This is a
   logical invariant, not a model judgment.

2. **Severity anchoring**: If issue_type=none (no visible damage), severity must be
   none. If evidence_standard_met=false, severity must be unknown.

3. **Image validity**: If non_original_image flag is present (watermark, stock photo,
   reused across users), valid_image must be false.

4. **Flag consolidation**: Merge flags from four sources —
   - Visual flags from Stage 2 (claim_mismatch, possible_manipulation, ...)
   - Chat flags from Stage 1 (text_instruction_present if instruction text detected)
   - Pgvector flags (non_original_image from reused-image detector, ADR-0004)
   - History flags from user_history.csv (user_history_risk)
   Then deduplicate and order canonically per RISK_FLAG_ORDER.

5. **Manual review trigger**: Set manual_review_required if user_history_risk OR any
   substantive evidence flag is present. Image-quality-only flags (low_quality_image)
   and a bare not_enough_information do not trigger manual review (ADR-0001).

6. **Enum normalization**: Validate all fields against allowed_values.py, convert
   bools to "true"/"false" strings, format supporting_image_ids and risk_flags as
   semicolon-separated or "none".

The rule layer is the final gatekeeper before output.csv: it ensures every row
conforms to the output schema and logical constraints, even if the model outputs are
inconsistent or incomplete.
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
    extra_visual_flags: set[str] | None = None,
) -> dict:
    """Combine Stage 1 + Stage 2 + history + extra flags → 10 predicted output fields.

    This is the rule layer's main entry point. It takes the raw model outputs and
    enforces all logical invariants, consolidates flags from all sources (visual,
    chat, pgvector, history), and normalizes enums/formats for output.csv.

    Args:
        stage1: Claim extraction output (claimed_parts, instruction_text_in_chat, ...)
        stage2: Visual verification output (claim_status, evidence_standard_met,
                risk_flags, severity, supporting_image_ids, ...)
        history_flags: Semicolon-separated flags from user_history.csv ("none" or
                       "user_history_risk;manual_review_required")
        image_ids: Available image IDs for this claim (e.g., ["img_001", "img_002"])
        extra_visual_flags: Optional deterministic flags from external detectors (e.g.
                            "non_original_image" from pgvector reused-image detection,
                            ADR-0004). Only recognized visual flags are honored.

    Returns:
        Dict with 10 output fields: evidence_standard_met,
        evidence_standard_met_reason, risk_flags, issue_type, object_part,
        claim_status, claim_status_justification, supporting_image_ids,
        valid_image, severity.

    Invariants enforced:
        - evidence_standard_met=false ⟹ claim_status=not_enough_information
        - evidence_standard_met=false ⟹ severity=unknown
        - issue_type=none ⟹ severity=none
        - non_original_image ⟹ valid_image=false
        - user_history_risk OR substantive flags ⟹ manual_review_required
    """
    # --- assemble base (visual + chat-injection) flags ---
    base = set(stage2.get("risk_flags", [])) & set(VISUAL_RISK_FLAGS)
    if stage1.get("instruction_text_in_chat"):
        base.add("text_instruction_present")
    if extra_visual_flags:
        base |= (set(extra_visual_flags) & set(VISUAL_RISK_FLAGS))

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
