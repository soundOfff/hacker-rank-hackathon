"""Per-claim orchestration: Stage 1 -> Stage 2 (single-routed) -> rule layer.

Modes:
- "routed" (shipped): a cheap up-front router (router.py) picks ONE Stage-2 model
            per claim — the default model for the easy majority, the escalation
            model for hard/adversarial rows — so each claim pays for exactly one
            Stage-2 call. ("tiered" is accepted as a back-compat alias.)
- "forced": Stage 2 = a single fixed model, no routing (used to compare
            Sonnet-all vs Opus-all in evaluation).
"""

from __future__ import annotations

import concurrent.futures as cf
import sys
from dataclasses import dataclass, field

from . import datasets, router, rules, vectorstore
from .allowed_values import INPUT_COLUMNS
from .config import (
    SETTINGS,
    STAGE1_MODEL,
    STAGE2_DEFAULT_MODEL,
    STAGE2_ESCALATION_MODEL,
)
from .images import encode_image
from .llm import Caller, Usage
from .stage1_extract import extract_claim_intent
from .stage2_vision import assess, build_system


@dataclass
class ClaimResult:
    row: dict
    usage: Usage
    model_used: str
    escalated: bool
    usage_by_model: dict = field(default_factory=dict)
    error: str | None = None


def _merge_by_model(target: dict, model: str, u: Usage) -> None:
    target.setdefault(model, Usage()).add(u)


def _encode_images(claim_row: dict):
    encoded = []
    for rel in datasets.parse_image_paths(claim_row["image_paths"]):
        iid = datasets.image_id(rel)
        encoded.append(encode_image(datasets.resolve_image(rel), iid))
    return encoded


def _fallback_predicted(history_flags: str) -> dict:
    base: set[str] = set()
    flags = set()
    if rules.derive_user_history_risk(history_flags):
        flags.add("user_history_risk")
    flags.add("manual_review_required")
    return {
        "evidence_standard_met": "false",
        "evidence_standard_met_reason": "Automated review failed; flagged for manual review.",
        "risk_flags": rules.canonical_flags(flags),
        "issue_type": "unknown",
        "object_part": "unknown",
        "claim_status": "not_enough_information",
        "claim_status_justification": "Automated review could not be completed for this claim.",
        "supporting_image_ids": "none",
        "valid_image": "false",
        "severity": "unknown",
    }


def process_claim(
    caller: Caller,
    claim_row: dict,
    user_history: dict,
    system_text: str,
    *,
    mode: str,
    default_model: str,
    escalation_model: str,
    effort: str | None,
    thinking: bool,
    store: "vectorstore.VectorStore | None" = None,
) -> ClaimResult:
    usage = Usage()
    by_model: dict = {}

    def acc(model: str, u: Usage) -> None:
        usage.add(u)
        _merge_by_model(by_model, model, u)

    hist_flags = user_history.get(claim_row["user_id"], {}).get("history_flags", "none")
    base_row = {c: claim_row.get(c, "") for c in INPUT_COLUMNS}

    try:
        transcript = claim_row["user_claim"]
        s1 = extract_claim_intent(caller, transcript)
        acc(STAGE1_MODEL, s1.usage)

        encoded = _encode_images(claim_row)
        image_ids = [im.image_id for im in encoded]
        if not encoded:
            raise RuntimeError("no images for claim")

        def run_stage2(model):
            return assess(
                caller,
                claim_object=claim_row["claim_object"],
                intent=s1.data,
                transcript=transcript,
                encoded=encoded,
                system_text=system_text,
                model=model,
                effort=effort,
                thinking=thinking,
            )

        # Pick exactly ONE Stage-2 model up-front, then run it once. "forced"
        # pins the model; "routed" (shipped) / "tiered" (back-compat alias) let
        # the cheap router escalate hard rows before any vision call — no
        # Sonnet-then-Opus double-pay (ADR-0003).
        if mode == "forced":
            model_used, escalated = default_model, False
        else:
            route = router.choose_model(
                stage1=s1.data,
                history_flags=hist_flags,
                default_model=default_model,
                escalation_model=escalation_model,
                settings=SETTINGS,
            )
            model_used, escalated = route.model, route.escalated

        s2 = run_stage2(model_used)
        acc(model_used, s2.usage)

        # Optional pgvector pre-pass: flag images reused across users (ADR-0004).
        extra_flags: set[str] = set()
        if store is not None:
            try:
                extra_flags = store.flag_reused(claim_row)
            except Exception:
                extra_flags = set()  # vector store is best-effort, never fatal

        predicted = rules.finalize(
            stage1=s1.data, stage2=s2.data, history_flags=hist_flags,
            image_ids=image_ids, extra_visual_flags=extra_flags,
        )
        row = {**base_row, **predicted}
        return ClaimResult(row=row, usage=usage, model_used=model_used,
                           escalated=escalated, usage_by_model=by_model)

    except Exception as exc:  # never drop a row from output.csv
        row = {**base_row, **_fallback_predicted(hist_flags)}
        return ClaimResult(row=row, usage=usage, model_used=default_model,
                           escalated=False, usage_by_model=by_model, error=str(exc))


def run(
    caller: Caller,
    claims: list[dict],
    user_history: dict,
    requirements_text: str,
    *,
    mode: str = "routed",
    default_model: str = STAGE2_DEFAULT_MODEL,
    escalation_model: str = STAGE2_ESCALATION_MODEL,
    effort: str | None = None,
    thinking: bool | None = None,
    max_workers: int | None = None,
    progress: bool = True,
) -> tuple[list[ClaimResult], Usage]:
    system_text = build_system(requirements_text)
    effort = SETTINGS.stage2_effort if effort is None else effort
    thinking = SETTINGS.stage2_thinking if thinking is None else thinking
    max_workers = max_workers or SETTINGS.max_workers

    # Optional pgvector reused-image detection (ADR-0004): index every image once
    # up-front (sequential, no write race), then the threaded pass only reads.
    store = None
    if vectorstore.enabled():
        try:
            store = vectorstore.VectorStore()
            store.ensure_schema()
            n = store.index_claims(claims)
            print(f"[vectorstore] indexed {n} images; reused-image detection enabled "
                  f"({store.backend}, dim={store.dim})", file=sys.stderr)
        except Exception as exc:
            print(f"[vectorstore] disabled (init failed: {exc})", file=sys.stderr)
            store = None

    results: list[ClaimResult | None] = [None] * len(claims)
    total_by_model: dict = {}

    def work(i: int):
        return i, process_claim(
            caller, claims[i], user_history, system_text,
            mode=mode, default_model=default_model, escalation_model=escalation_model,
            effort=effort, thinking=thinking, store=store,
        )

    done = 0
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(work, i) for i in range(len(claims))]
        for fut in cf.as_completed(futures):
            i, res = fut.result()
            results[i] = res
            for m, u in res.usage_by_model.items():
                _merge_by_model(total_by_model, m, u)
            done += 1
            if progress:
                tag = "ERR" if res.error else ("ESC" if res.escalated else "ok")
                print(f"[{done}/{len(claims)}] {claims[i]['user_id']} {claims[i]['claim_object']} -> {res.row['claim_status']} ({tag})", file=sys.stderr)

    return [r for r in results if r is not None], total_by_model
