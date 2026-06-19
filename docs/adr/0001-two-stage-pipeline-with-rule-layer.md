---
status: accepted
---

# Two-stage VLM pipeline with a deterministic rule layer

We verify each damage claim with a **two-stage model pipeline** — Stage 1 (Haiku
4.5, text-only) extracts a language-normalized claim intent from the multilingual
chat and flags manipulation text; Stage 2 (Sonnet 4.6 by default, Opus 4.8 on
low-confidence rows) makes the visual judgment from the images — followed by a
**deterministic Python rule layer** (Stage 3) that owns everything that should
not be left to a model: the user-history flags, the evidence/status invariant,
severity anchoring, enum normalization, and CSV formatting. We chose this over a
single all-in-one VLM call because the rule layer makes the non-visual logic
reproducible and trivially defensible, and the split lets us evaluate and tune
each stage independently — at the cost of ~2 model calls per claim, which is
negligible at this scale (64 claims).

## Considered options

- **Single structured VLM call per claim.** Simplest and cheapest, but folds
  history reasoning and field-consistency into the model, making the run
  non-reproducible and hard to defend in the judge interview.
- **Two-stage pipeline + rule layer (chosen).** More calls and orchestration,
  but the deterministic core is testable against the labeled samples without any
  API access, and each stage is independently evaluable.

## Consequences

- The deterministic rules below are validated against **100% of the 20 labeled
  samples** and unit-tested (`code/tests/test_rules.py`) with no API key:
  - `evidence_standard_met = false ⟺ claim_status = not_enough_information`;
    when false, `severity = unknown`.
  - `user_history_risk` flag ⟺ the user's `history_flags` contains
    `user_history_risk`.
  - `manual_review_required` ⟺ the user's history carries
    `user_history_risk`/`manual_review_required`, **or** a substantive risk flag
    is present (`claim_mismatch`, `wrong_object`, `wrong_object_part`,
    `non_original_image`, `possible_manipulation`, `text_instruction_present`).
    Image-quality-only flags and a bare NEI do **not** trigger it.
  - `issue_type = none ⟹ severity = none`; `non_original_image ⟹ valid_image = false`.
  - User history never changes `issue_type`, `object_part`, `claim_status`, or
    `severity`.
- Instruction/manipulation text in **either** the chat or an image is flagged
  `text_instruction_present`, ignored as data, and never moves the verdict toward
  the user's favor.
- `valid_image` is an independent authenticity/usability judgment, not coupled to
  `claim_status`.
