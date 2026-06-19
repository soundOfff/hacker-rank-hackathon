#!/usr/bin/env python3
"""Entry point — run the claim-verification pipeline on dataset/claims.csv and
write output.csv.

Examples:
    python code/main.py                          # routed config -> ./output.csv
    python code/main.py --limit 3                # smoke test on 3 rows
    python code/main.py --mode forced --model anthropic/claude-sonnet-4.6
    python code/main.py --output dataset/output.csv
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # put code/ on path

from orchestrate import costs, datasets
from orchestrate.config import (
    DATASET_DIR,
    REPO_ROOT,
    SETTINGS,
    STAGE2_DEFAULT_MODEL,
    STAGE2_ESCALATION_MODEL,
)
from orchestrate.llm import Caller
from orchestrate.pipeline import run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(DATASET_DIR / "claims.csv"))
    ap.add_argument("--output", default=str(REPO_ROOT / "output.csv"))
    ap.add_argument("--mode", choices=["routed", "forced"], default="routed")
    ap.add_argument("--model", default=STAGE2_DEFAULT_MODEL,
                    help="Stage-2 model when --mode forced")
    ap.add_argument("--limit", type=int, default=None, help="process only the first N claims")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-cache", action="store_true", help="ignore the on-disk response cache")
    args = ap.parse_args()

    if args.no_cache:
        SETTINGS.use_cache = False

    claims = datasets.load_claims(Path(args.input))
    if args.limit:
        claims = claims[: args.limit]
    history = datasets.load_user_history(DATASET_DIR / "user_history.csv")
    reqs_text = datasets.format_requirements(
        datasets.load_evidence_requirements(DATASET_DIR / "evidence_requirements.csv")
    )

    caller = Caller()
    default_model = args.model if args.mode == "forced" else STAGE2_DEFAULT_MODEL
    results, by_model = run(
        caller, claims, history, reqs_text,
        mode=args.mode,
        default_model=default_model,
        escalation_model=STAGE2_ESCALATION_MODEL,
        max_workers=args.workers,
    )

    rows = [r.row for r in results]
    out_path = Path(args.output)
    datasets.write_output_csv(out_path, rows)

    # ---- summary to stderr ----
    n = len(results)
    esc = sum(1 for r in results if r.escalated)
    err = sum(1 for r in results if r.error)
    dist = Counter(r.row["claim_status"] for r in results)
    summary = costs.summarize(by_model)

    print(f"\nWrote {n} rows -> {out_path}", file=sys.stderr)
    print(f"claim_status: {dict(dist)}", file=sys.stderr)
    print(f"routed to Opus: {esc} | errors (fallback rows): {err}", file=sys.stderr)
    print("\nToken usage / estimated cost:", file=sys.stderr)
    for row in summary["rows"]:
        print(
            f"  {row['model']:<20} in={row['input']:>7} out={row['output']:>6} "
            f"cache_r={row['cache_read']:>7} cache_w={row['cache_write']:>6} "
            f"~${row['cost']:.4f}",
            file=sys.stderr,
        )
    print(f"  TOTAL estimated cost: ~${summary['totals']['cost']:.4f}", file=sys.stderr)


if __name__ == "__main__":
    main()
