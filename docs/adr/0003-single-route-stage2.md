---
status: accepted
supersedes: the tiered confidence-escalation strategy described in ADR-0001 / code/README.md
---

# Single-route Stage-2 model selection (no double-pay)

Each claim now pays for **exactly one** Stage-2 (vision) call. The model is
chosen *before* that call by a cheap, deterministic router (`orchestrate/router.py`),
or pinned with `--mode forced`. The shipped default is **cost-first**: Sonnet 4.6
on every claim.

## Context — the old tiered config was cost-negative

The previous "tiered" strategy always ran Sonnet 4.6, then *re-ran* Opus 4.8 on
top whenever Sonnet returned low/medium confidence or certain flags. Measured on
the 20-row sample that escalated 15/20 rows, so it paid for **two** Stage-2 calls
on most claims:

| Config (single-route unless noted) | Est. cost (20 rows) | Proj. cost (44) | `claim_status` acc |
|---|---|---|---|
| sonnet_all (**shipped default**) | $0.4116 | ~$0.91 | 70% |
| routed (text/history triggers armed) | $0.4945 | ~$1.09 | 70% |
| opus_all (accuracy-first) | $0.7097 | ~$1.56 | 80% |
| _old tiered (Sonnet **and** Opus, double-pay)_ | _$0.9484_ | _~$2.09_ | _80%_ |

The old tiered config cost **more than Opus-all for the same 80% accuracy** — a
strict loss. Tiering only pays off at a low escalation rate; at 15/20 it was pure
waste.

## Decision

1. **One Stage-2 call per claim.** Pick the model up-front; never run two frontier
   models on the same row.
2. **Ship cost-first (Sonnet on every claim).** Cheapest at ~$0.91/44 (−57% vs the
   old $2.09) and, on this sample, matches the routed accuracy at lower cost.
3. **Keep the router, armed but with triggers off by default.** `router.py`
   escalates a row to Opus when a cheap pre-Stage-2 signal fires
   (`instruction_text_in_chat`, `is_multi_part`, `user_history_risk`), toggled via
   `ORCH_ROUTE_ON_*`.

## Why the text/history router is dominated (today)

On the sample, the only two rows Opus uniquely fixes (`user_001`, `user_004`) are
**image-hard, not text-hard**: textually trivial, single-part, clean-history
claims (`risk_flags: none`) where Sonnet wrongly calls a valid claim
`contradicted` and only Opus reads the photo correctly. No Stage-1/history signal
can distinguish them, so the router escalates the *wrong* rows — paying Opus
prices without the accuracy, i.e. dominated by Sonnet-all.

The best signal (Stage-2 confidence + visual flags) is only available *after* a
vision call — using it is what created the double-pay in the first place.

## Consequences

- The shipped run is reproducible and ~2.3× cheaper than the old config.
- Accuracy-first is one flag away: `--mode forced --model anthropic/claude-opus-4.8`.
- The router is the designated home for a **cheap image signal**: the CLIP
  image-vs-claim-object similarity from the pgvector store (ADR-0004) can flag
  "the photo may not match the claim" *before* Stage 2 — the missing pre-vision
  trigger that would let routing reach Opus accuracy near Sonnet cost. Until that
  lands, text/history triggers ship off.
- `router.choose_model` is pure and unit-tested (`code/tests/test_router.py`).
