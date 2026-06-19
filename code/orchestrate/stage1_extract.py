"""Stage 1 — Claim Intent Extraction (text-only, Haiku 4.5).

Normalizes the multilingual chat transcript to a canonical claim intent in English:
  - claimed_parts: the object parts the user claims are damaged
  - claimed_issues: the damage types the user describes
  - claim_summary: normalized English summary of the claim
  - is_multi_part: whether the claim spans multiple parts (escalation signal)
  - instruction_text_in_chat: whether the chat contains adversarial instruction text
    (e.g., "approve this claim", "ignore previous instructions")

Handles mixed scripts (Hindi/Hinglish, Spanish, Chinese pinyin, code-switched text).
Output is structured JSON validated against stage1_schema().

The extraction is text-only (no images) and runs on Haiku 4.5 with no reasoning
budget — fast and cheap. Stage 2 uses this intent as context alongside the images.
"""

from __future__ import annotations

from pathlib import Path

from .config import STAGE1_MODEL, SETTINGS
from .llm import Caller, CallResult
from .schema import SCHEMA_VERSION, stage1_schema

_PROMPT = (Path(__file__).parent / "prompts" / "stage1_system.md").read_text(encoding="utf-8")


def extract_claim_intent(caller: Caller, transcript: str) -> CallResult:
    schema = stage1_schema()
    user_content = [{"type": "text", "text": "Transcript:\n" + transcript}]
    return caller.structured(
        model=STAGE1_MODEL,
        system_text=_PROMPT,
        user_content=user_content,
        schema=schema,
        max_tokens=SETTINGS.stage1_max_tokens,
        effort=None,      # text-only extraction: no reasoning budget needed
        thinking=False,
        cache_payload={
            "stage": "1",
            "schema": SCHEMA_VERSION,
            "prompt": _PROMPT,
            "transcript": transcript,
            "max_tokens": SETTINGS.stage1_max_tokens,
        },
    )
