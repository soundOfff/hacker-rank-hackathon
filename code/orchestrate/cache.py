"""Tiny on-disk JSON cache keyed by a hash of the full request.

Makes re-runs free and reproducible: identical inputs (model, prompt, schema,
image bytes) always return the same stored response, so iterating on the rule
layer or eval never re-pays for model calls.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .config import CACHE_DIR, SETTINGS


def cache_key(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get(key: str) -> Optional[dict]:
    if not SETTINGS.use_cache:
        return None
    p = _path(key)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def put(key: str, value: dict) -> None:
    if not SETTINGS.use_cache:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(key).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
    tmp.replace(_path(key))
