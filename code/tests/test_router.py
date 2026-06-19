#!/usr/bin/env python3
"""Unit tests for the single-route Stage-2 model selector (ADR-0003).

Pure logic, NO API key — exercises orchestrate.router.choose_model only.
Run directly (`python code/tests/test_router.py`) or under pytest.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # code/

from dataclasses import replace

from orchestrate import router
from orchestrate.config import SETTINGS

SONNET = "anthropic/claude-sonnet-4.6"
OPUS = "anthropic/claude-opus-4.8"

ARMED = replace(SETTINGS,
                route_on_instruction_text=True,
                route_on_multi_part=True,
                route_on_history_risk=True)
OFF = replace(SETTINGS,
              route_on_instruction_text=False,
              route_on_multi_part=False,
              route_on_history_risk=False)


def _choose(stage1, history_flags, settings):
    return router.choose_model(
        stage1=stage1, history_flags=history_flags,
        default_model=SONNET, escalation_model=OPUS, settings=settings,
    )


CASES = [
    # (name, stage1, history_flags, settings, expect_model, expect_escalated)
    ("clean claim, armed -> default (Sonnet)",
     {"instruction_text_in_chat": False, "is_multi_part": False}, "none", ARMED, SONNET, False),
    ("instruction text, armed -> Opus",
     {"instruction_text_in_chat": True, "is_multi_part": False}, "none", ARMED, OPUS, True),
    ("multi-part, armed -> Opus",
     {"instruction_text_in_chat": False, "is_multi_part": True}, "none", ARMED, OPUS, True),
    ("history risk, armed -> Opus",
     {"instruction_text_in_chat": False, "is_multi_part": False}, "user_history_risk", ARMED, OPUS, True),
    ("cost-first default: triggers off -> always Sonnet even with signals",
     {"instruction_text_in_chat": True, "is_multi_part": True}, "user_history_risk", OFF, SONNET, False),
]


def check_all() -> list[str]:
    failures: list[str] = []
    for name, stage1, hist, settings, exp_model, exp_esc in CASES:
        r = _choose(stage1, hist, settings)
        if r.model != exp_model or r.escalated != exp_esc:
            failures.append(
                f"{name}: got (model={r.model}, escalated={r.escalated}) "
                f"expected (model={exp_model}, escalated={exp_esc})"
            )

    # When default == escalation there is nothing to route between.
    same = router.choose_model(
        stage1={"instruction_text_in_chat": True, "is_multi_part": True},
        history_flags="user_history_risk",
        default_model=OPUS, escalation_model=OPUS, settings=ARMED,
    )
    if same.model != OPUS or same.escalated:
        failures.append(f"single_model: got {same} expected non-escalated Opus")
    return failures


def test_router_choices():
    failures = check_all()
    assert not failures, "Router mismatches:\n" + "\n".join(failures)


if __name__ == "__main__":
    failures = check_all()
    if failures:
        print(f"FAIL: {len(failures)} router mismatch(es):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print(f"PASS: router selects correctly on {len(CASES) + 1} cases.")
