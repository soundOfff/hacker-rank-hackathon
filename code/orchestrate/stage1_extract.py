"""Stage 1 — claim intent extraction from the (multilingual) chat transcript."""

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
