"""Response cache keyed by SHA-256 hash of the full request.

Makes re-runs free and reproducible: identical inputs (model, prompt, schema, image
bytes, max_tokens) always return the same cached response with zero API calls. This
means iterating on the rule layer, regenerating output.csv, or re-running evaluation
never re-pays for model calls — only the first run per unique input hits the API.

Pluggable backend architecture for scale:

- **Filesystem** (default): On-disk JSON under ``.cache/responses/`` — zero setup,
  works immediately, per-machine. Each key is a separate file (SHA-256.json).

- **Redis** (when REDIS_URL env var is set): Shared cache across workers, containers,
  and machines. Essential for distributed runs on large datasets (1000s of claims).
  Falls back to filesystem if Redis is unreachable, so a run never hard-fails just
  because the cache service is down.

The public API (cache_key, get, put) is backend-agnostic: callers hash the request
payload and get/put responses without knowing which backend is active. The backend
is chosen once at module load time based on environment.

Cache key includes: stage, model, prompt, schema version, user content (incl. image
hashes), max_tokens, effort, thinking. Changing any input invalidates the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from .config import CACHE_DIR, SETTINGS


def cache_key(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class _FilesystemBackend:
    """On-disk JSON, one file per key. The original (default) backend."""

    name = "filesystem"

    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        p = self._path(key)
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def put(self, key: str, value: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(key).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        tmp.replace(self._path(key))


class _RedisBackend:
    """Shared cache in Redis. Values are JSON strings under a namespaced key."""

    name = "redis"

    def __init__(self, url: str, prefix: str = "orch:cache:"):
        import redis  # imported lazily so the base install needs no redis dep

        self.client = redis.Redis.from_url(url, socket_connect_timeout=3)
        self.client.ping()  # fail fast -> caller falls back to filesystem
        self.prefix = prefix

    def get(self, key: str) -> Optional[dict]:
        try:
            raw = self.client.get(self.prefix + key)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def put(self, key: str, value: dict) -> None:
        try:
            self.client.set(self.prefix + key, json.dumps(value, ensure_ascii=False))
        except Exception:
            pass  # cache writes are best-effort; never fail the run on a cache hiccup


def _make_backend():
    url = os.environ.get("REDIS_URL")
    if url:
        try:
            backend = _RedisBackend(url)
            print("[cache] using Redis backend (REDIS_URL)", file=sys.stderr)
            return backend
        except Exception as exc:
            print(
                f"[cache] REDIS_URL set but Redis is unavailable ({exc}); "
                "falling back to the filesystem cache.",
                file=sys.stderr,
            )
    return _FilesystemBackend(CACHE_DIR)


_BACKEND = None


def _backend():
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _make_backend()
    return _BACKEND


def get(key: str) -> Optional[dict]:
    if not SETTINGS.use_cache:
        return None
    return _backend().get(key)


def put(key: str, value: dict) -> None:
    if not SETTINGS.use_cache:
        return
    _backend().put(key, value)
