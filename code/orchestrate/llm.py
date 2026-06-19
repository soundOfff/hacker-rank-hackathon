"""Thin wrapper around the OpenRouter Chat Completions API (OpenAI-compatible).

OpenRouter's recommended Python transport is the OpenAI SDK pointed at
``https://openrouter.ai/api/v1`` — that is what we use here, so the pipeline is
provider-portable while keeping every Anthropic feature we relied on (see
ADR-0002).

Responsibilities:
- structured outputs via ``response_format={"type": "json_schema", ...}`` with
  ``strict: true`` (guaranteed-valid enums; supported for Claude Sonnet 4.5+/
  Opus 4.1+ and OpenAI/Gemini/most OSS models through OpenRouter)
- prompt caching on the (stable) system prompt via Anthropic ``cache_control``
  breakpoints, which OpenRouter passes through
- reasoning/thinking via OpenRouter's unified ``reasoning`` parameter, with a
  defensive fallback if a model/provider rejects it
- usage accounting (incl. cached / cache-write tokens) for the operational
  analysis
- on-disk response caching (keyed by the full request)

The SDK already retries 429/5xx with backoff (max_retries on the client).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import openai

from . import cache
from .config import (
    OPENROUTER_APP_NAME,
    OPENROUTER_BASE_URL,
    OPENROUTER_SITE_URL,
    SETTINGS,
    require_api_key,
)
from .usage import Usage  # re-exported for backwards-compatible imports

# Map the human-facing effort knob to an Anthropic thinking budget (tokens).
# Used only when thinking is enabled.
_EFFORT_BUDGET = {"low": 1024, "medium": 2048, "high": 4096, "max": 8192}


@dataclass
class CallResult:
    data: dict
    usage: Usage
    model: str
    cached: bool = False


def _reasoning_budget(effort: Optional[str], thinking: bool) -> Optional[int]:
    """Thinking budget (tokens) for this call, or None to disable reasoning.

    For Anthropic, OpenRouter maps ``reasoning.max_tokens`` to the thinking
    budget, and the top-level ``max_tokens`` is the ceiling for *thinking +
    visible output combined*. So the caller adds this budget *on top of* the
    requested output ``max_tokens`` to guarantee full output headroom (otherwise
    a large thinking budget starves the JSON answer and truncates it).
    """
    if not thinking:
        return None
    return _EFFORT_BUDGET.get(effort or "medium", 2048)


@dataclass
class Caller:
    client: openai.OpenAI = field(default=None)

    def __post_init__(self):
        if self.client is None:
            api_key = require_api_key()
            default_headers = {}
            if OPENROUTER_SITE_URL:
                default_headers["HTTP-Referer"] = OPENROUTER_SITE_URL
            if OPENROUTER_APP_NAME:
                default_headers["X-Title"] = OPENROUTER_APP_NAME
            self.client = openai.OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=api_key,
                max_retries=SETTINGS.max_retries,
                default_headers=default_headers or None,
            )

    def structured(
        self,
        *,
        model: str,
        system_text: str,
        user_content: list[dict],
        schema: dict,
        max_tokens: int,
        effort: Optional[str] = None,
        thinking: bool = False,
        cache_payload: Optional[dict] = None,
    ) -> CallResult:
        """One structured call. Returns parsed JSON + usage.

        cache_payload, if given, is hashed for the on-disk cache (it should fully
        determine the request: model, prompts, schema version, image hashes...).
        """
        if cache_payload is not None:
            key = cache.cache_key({"model": model, **cache_payload})
            hit = cache.get(key)
            if hit is not None:
                return CallResult(
                    data=hit["data"],
                    usage=Usage(**hit.get("usage", {})),
                    model=model,
                    cached=True,
                )

        data, usage = self._create(
            model=model,
            system_text=system_text,
            user_content=user_content,
            schema=schema,
            max_tokens=max_tokens,
            effort=effort,
            thinking=thinking,
        )

        if cache_payload is not None:
            cache.put(key, {"data": data, "usage": usage.as_dict()})
        return CallResult(data=data, usage=usage, model=model)

    def _create(self, *, model, system_text, user_content, schema, max_tokens,
                effort, thinking) -> tuple[dict, Usage]:
        # System prompt as a single cache breakpoint: byte-identical across every
        # call, so OpenRouter writes it once and reads it back at ~0.1x.
        system_message = {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "evidence_review",
                "strict": True,
                "schema": schema,
            },
        }
        # OpenRouter returns full usage automatically; the include flag is
        # deprecated, so extra_body only carries the optional reasoning budget.
        budget = _reasoning_budget(effort, thinking)
        extra_body: dict[str, Any] = {}
        api_max_tokens = max_tokens
        if budget is not None:
            extra_body["reasoning"] = {"max_tokens": budget}
            api_max_tokens = max_tokens + budget  # reserve full output room on top of thinking

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=api_max_tokens,
            messages=[system_message, {"role": "user", "content": user_content}],
            response_format=response_format,
        )
        if extra_body:
            kwargs["extra_body"] = extra_body

        try:
            resp = self.client.chat.completions.create(**kwargs)
        except openai.BadRequestError:
            # The reasoning passthrough is the only optional part. If it wasn't
            # set, the 400 is something else (bad slug / schema / image) — surface
            # it rather than blindly resending the identical request.
            if extra_body.pop("reasoning", None) is None:
                raise
            kwargs["max_tokens"] = max_tokens
            kwargs.pop("extra_body", None)
            resp = self.client.chat.completions.create(**kwargs)

        choice = resp.choices[0] if resp.choices else None
        if choice is None:
            raise RuntimeError(f"No choices in response from {model}")
        if getattr(choice, "finish_reason", None) == "length":
            # Truncated before the JSON closed; a partial parse would raise a
            # cryptic JSONDecodeError, so fail with an actionable message.
            raise RuntimeError(
                f"Truncated output (finish_reason=length) from {model}; "
                "increase the stage max_tokens."
            )
        text = choice.message.content
        if not text:
            raise RuntimeError(f"No content in response from {model}")
        data = json.loads(text)
        return data, Usage.from_openrouter(getattr(resp, "usage", None))
