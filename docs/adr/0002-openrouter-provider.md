---
status: accepted
---

# Serve the models through OpenRouter (OpenAI-compatible transport)

We call the models through **OpenRouter** instead of the Anthropic SDK directly.
OpenRouter exposes an OpenAI-compatible Chat Completions API, and its recommended
Python transport is the **OpenAI SDK pointed at `https://openrouter.ai/api/v1`** —
so `code/orchestrate/llm.py` now constructs `openai.OpenAI(base_url=...)` and reads
`OPENROUTER_API_KEY`. The two-stage-pipeline + rule-layer architecture (ADR-0001)
is unchanged; only the model transport moves.

The default model slugs route to the same Claude models as before
(`anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-4.6`,
`anthropic/claude-opus-4.8`), so behavior is preserved by default. Every slug is
overridable via env (`ORCH_STAGE1_MODEL`, `ORCH_STAGE2_MODEL`,
`ORCH_STAGE2_ESCALATION_MODEL`), which is the point: one account/key now reaches
Claude, GPT, Gemini, and open-weight models behind a single interface, making the
default-vs-escalation tier and any future model swap a config change rather than a
client rewrite.

## Feature mapping (Anthropic-native → OpenRouter)

- **Structured outputs.** `output_config.format` →
  `response_format={"type":"json_schema","json_schema":{"name","strict":true,"schema"}}`.
  Supported through OpenRouter for Claude Sonnet 4.5+/Opus 4.1+, OpenAI GPT-4o+,
  Gemini, and most OSS models. Our schemas already use `additionalProperties:false`
  with all properties `required`, which strict mode needs, so enums stay pinned.
- **Prompt caching.** Anthropic `cache_control` breakpoints are passed through:
  the (stable) system prompt is sent as a single `{"type":"text",...,"cache_control":{"type":"ephemeral"}}`
  block, written once and read back at ~0.1×. Cached usage is reported under
  `usage.prompt_tokens_details.cached_tokens` / `cache_write_tokens`, which
  `Usage.from_openrouter` splits back into fresh / cache-read / cache-write so the
  cost model is unchanged.
- **Reasoning / thinking.** Adaptive thinking → OpenRouter's unified `reasoning`
  parameter (`extra_body={"reasoning": {"max_tokens": budget}}`), with the budget
  derived from the existing effort tier and capped below the response `max_tokens`.
  Stage 1 (text-only) sends no reasoning. If a model/provider rejects the
  passthrough, `_create` retries once without it — structured output and caching,
  the load-bearing parts, always remain.
- **Images.** Anthropic `image` source blocks → OpenAI `image_url` parts with
  base64 `data:` URIs.

## Consequences

- One dependency change: `anthropic` → `openai` in `requirements.txt`; the secret
  is now `OPENROUTER_API_KEY` (a generic `OPENAI_API_KEY` is also accepted).
- The on-disk response cache, deterministic rule layer, and `tests/test_rules.py`
  (no API key) are untouched and still pass.
- Cost estimates remain list-price approximations; OpenRouter may add a small
  routing fee, so treat `costs.py` output as a lower bound for the operational
  analysis.
