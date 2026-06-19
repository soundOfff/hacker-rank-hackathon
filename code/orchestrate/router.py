"""Single-route Stage-2 model selection (ADR-0003).

Picks exactly ONE Stage-2 model per claim *before* any vision call, from cheap
pre-Stage-2 signals (the Stage-1 extraction + the user's history). The pricier
escalation model is reserved for the hard/adversarial minority; everything else
runs the default model.

This replaces the old confidence-escalation path, which always ran the default
model and *then* re-ran the escalation model on top — paying for two Stage-2
calls on every escalated row. The routing signals here are all known *before*
Stage 2, so each claim pays for exactly one Stage-2 call.
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
