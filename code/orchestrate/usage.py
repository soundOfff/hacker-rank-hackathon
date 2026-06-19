"""Token-usage accumulator (no third-party deps so cost tooling and tests can
import it without the model SDK)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _get(obj: Any, name: str, default: int = 0) -> int:
    """Read ``name`` from an object attribute or a dict key; coerce None->0."""
    if obj is None:
        return default
    val = getattr(obj, name, None)
    if val is None and isinstance(obj, dict):
        val = obj.get(name)
    return int(val) if val is not None else default


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @classmethod
    def from_openrouter(cls, usage: Any) -> "Usage":
        """Map an OpenAI/OpenRouter ``usage`` object to our accounting fields.

        OpenRouter reports ``prompt_tokens`` as the *total* input count, with the
        cache breakdown under ``prompt_tokens_details`` (``cached_tokens`` = cache
        reads, ``cache_write_tokens`` = cache creation); some providers also
        surface cache creation top-level as ``cache_creation_input_tokens``, so we
        read both. We split the total into three disjoint buckets — fresh / cache
        read / cache write — so costs.py can price fresh at full rate, reads at
        ~0.1x, and writes at ~1.25x with no overlap (the Anthropic semantics the
        cost model was written against).

        Assumption: ``prompt_tokens`` is the full count including cache-write
        tokens (per OpenRouter's usage-accounting docs), so ``fresh = prompt -
        cached - cache_write``. The cost is a list-price estimate for the
        operational analysis; if a provider instead reports ``prompt_tokens``
        exclusive of cache writes, the only effect is a sub-cent under-estimate of
        fresh input on the single first (cache-writing) call of a run.
        """
        if usage is None:
            return cls()
        prompt = _get(usage, "prompt_tokens")
        completion = _get(usage, "completion_tokens")
        details = getattr(usage, "prompt_tokens_details", None)
        if details is None and isinstance(usage, dict):
            details = usage.get("prompt_tokens_details")
        cached = _get(details, "cached_tokens")
        cache_write = _get(details, "cache_write_tokens") or _get(usage, "cache_creation_input_tokens")
        fresh = max(prompt - cached - cache_write, 0)
        return cls(
            input_tokens=fresh,
            output_tokens=completion,
            cache_read_input_tokens=cached,
            cache_creation_input_tokens=cache_write,
        )

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
        }
