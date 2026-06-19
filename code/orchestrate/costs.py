"""Token -> USD cost estimation for the operational analysis.

Uses list pricing from config. Uncached input at full price, cache reads at
~0.1x, cache writes at ~1.25x.
"""

from __future__ import annotations

from .config import CACHE_READ_MULT, CACHE_WRITE_MULT, PRICING
from .usage import Usage


def cost_for(model: str, u: Usage) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0
    inp = p["input"] / 1_000_000
    out = p["output"] / 1_000_000
    cost = u.input_tokens * inp + u.output_tokens * out
    cost += u.cache_read_input_tokens * inp * CACHE_READ_MULT
    cost += u.cache_creation_input_tokens * inp * CACHE_WRITE_MULT
    return cost


def summarize(by_model: dict) -> dict:
    rows = []
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0}
    for model, u in sorted(by_model.items()):
        c = cost_for(model, u)
        rows.append({
            "model": model,
            "input": u.input_tokens,
            "output": u.output_tokens,
            "cache_read": u.cache_read_input_tokens,
            "cache_write": u.cache_creation_input_tokens,
            "cost": c,
        })
        totals["input"] += u.input_tokens
        totals["output"] += u.output_tokens
        totals["cache_read"] += u.cache_read_input_tokens
        totals["cache_write"] += u.cache_creation_input_tokens
        totals["cost"] += c
    return {"rows": rows, "totals": totals}
