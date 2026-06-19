"""Single-route Stage-2 Model Selection (ADR-0003).

Picks exactly ONE Stage-2 model per claim *before* any vision call, using cheap
pre-Stage-2 signals (Stage-1 extraction + user history). No double-pay: each claim
pays for one Stage-2 call, not Sonnet-then-Opus.

Routing strategy (cost-first, shipped):
  - Default model (Sonnet 4.6): Easy majority of claims
  - Escalation model (Opus 4.8): Hard/adversarial minority

Escalation triggers (all configurable via ORCH_ROUTE_ON_* env vars):
  1. instruction_text_in_chat=true (adversarial prompt injection detected in Stage 1)
  2. is_multi_part=true (claim spans multiple parts → harder to assess)
  3. user_history_risk=true (risky history from user_history.csv)

Shipped default: All triggers OFF → Sonnet on every claim (~$0.91/44, 70% acc).
Accuracy-first: Force Opus on every claim (~$1.56/44, 80% acc) via --mode forced.

This replaces the old confidence-escalation config, which always ran Sonnet first,
then re-ran Opus on low-confidence rows — paying for two Stage-2 calls per escalated
claim (~$2.09/44). The routing signals here are all known *before* Stage 2, so we
pick the right model once and stop.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import rules
from .config import Settings


@dataclass
class Route:
    model: str
    escalated: bool   # True iff routed to the escalation (pricier) model
    reason: str       # trigger(s) that escalated, or "default" / "single_model"


def choose_model(
    *,
    stage1: dict,
    history_flags: str | None,
    default_model: str,
    escalation_model: str,
    settings: Settings,
) -> Route:
    """Decide the Stage-2 model for one claim. Pure / deterministic / no I/O."""
    if default_model == escalation_model:
        # Nothing to route between (e.g. the forced single-model eval configs).
        return Route(model=default_model, escalated=False, reason="single_model")

    reasons: list[str] = []
    if settings.route_on_instruction_text and stage1.get("instruction_text_in_chat"):
        reasons.append("instruction_text_in_chat")
    if settings.route_on_multi_part and stage1.get("is_multi_part"):
        reasons.append("multi_part_claim")
    if settings.route_on_history_risk and rules.derive_user_history_risk(history_flags):
        reasons.append("user_history_risk")

    if reasons:
        return Route(model=escalation_model, escalated=True, reason=",".join(reasons))
    return Route(model=default_model, escalated=False, reason="default")
