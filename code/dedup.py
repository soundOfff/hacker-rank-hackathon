#!/usr/bin/env python3
"""Entry point for the pgvector image dedup / reused-image store (ADR-0004).

Requires DATABASE_URL (a Postgres+pgvector instance) and the optional infra deps
(`pip install -r code/requirements-infra.txt`). With `docker compose`, both are
already wired.

    python code/dedup.py index     # embed + index every dataset image
    python code/dedup.py report    # print cross-user near-duplicate images
    python code/dedup.py reset     # drop the table
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # put code/ on path

from orchestrate import vectorstore


if __name__ == "__main__":
    raise SystemExit(vectorstore.cli(sys.argv[1:]))
