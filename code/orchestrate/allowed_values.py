"""Allowed values and output contract from problem_statement.md.

Single source of truth for every enum and the output column order. The Stage-2
schema (schema.py) and the rule layer (rules.py) both build on these so a label
can never drift out of the allowed set.
"""

CLAIM_OBJECTS = ["car", "laptop", "package"]

CLAIM_STATUS = ["supported", "contradicted", "not_enough_information"]

ISSUE_TYPES = [
    "dent", "scratch", "crack", "glass_shatter", "broken_part", "missing_part",
    "torn_packaging", "crushed_packaging", "water_damage", "stain", "none", "unknown",
]

OBJECT_PARTS = {
    "car": [
        "front_bumper", "rear_bumper", "door", "hood", "windshield", "side_mirror",
        "headlight", "taillight", "fender", "quarter_panel", "body", "unknown",
    ],
    "laptop": [
        "screen", "keyboard", "trackpad", "hinge", "lid", "corner", "port",
        "base", "body", "unknown",
    ],
    "package": [
        "box", "package_corner", "package_side", "seal", "label", "contents",
        "item", "unknown",
    ],
}

SEVERITY = ["none", "low", "medium", "high", "unknown"]

# Full risk-flag vocabulary (includes `none` and the two derived flags).
RISK_FLAGS = [
    "none", "blurry_image", "cropped_or_obstructed", "low_light_or_glare",
    "wrong_angle", "wrong_object", "wrong_object_part", "damage_not_visible",
    "claim_mismatch", "possible_manipulation", "non_original_image",
    "text_instruction_present", "user_history_risk", "manual_review_required",
]

# Flags the Stage-2 VLM may emit directly (image/visual evidence only).
# Excludes `none` (empty list == none) and the two flags the rule layer derives.
VISUAL_RISK_FLAGS = [
    "blurry_image", "cropped_or_obstructed", "low_light_or_glare", "wrong_angle",
    "wrong_object", "wrong_object_part", "damage_not_visible", "claim_mismatch",
    "possible_manipulation", "non_original_image", "text_instruction_present",
]

# Canonical output ordering for risk_flags (matches the labeled samples:
# evidence flags first, then user_history_risk, then manual_review_required last).
RISK_FLAG_ORDER = [
    "blurry_image", "cropped_or_obstructed", "low_light_or_glare", "wrong_angle",
    "wrong_object", "wrong_object_part", "damage_not_visible", "claim_mismatch",
    "possible_manipulation", "non_original_image", "text_instruction_present",
    "user_history_risk", "manual_review_required",
]

# Substantive flags that, on their own, warrant manual review (see ADR-0001).
SUBSTANTIVE_FLAGS = {
    "claim_mismatch", "wrong_object", "wrong_object_part", "non_original_image",
    "possible_manipulation", "text_instruction_present",
}

CLAIM_STATUS_NEI = "not_enough_information"

# Exact output schema, in order (problem_statement.md §Required output).
OUTPUT_COLUMNS = [
    "user_id", "image_paths", "user_claim", "claim_object",
    "evidence_standard_met", "evidence_standard_met_reason", "risk_flags",
    "issue_type", "object_part", "claim_status", "claim_status_justification",
    "supporting_image_ids", "valid_image", "severity",
]

# Pass-through input fields (copied verbatim, never predicted).
INPUT_COLUMNS = ["user_id", "image_paths", "user_claim", "claim_object"]
