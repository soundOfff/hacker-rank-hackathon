"""pgvector-backed image vector store for reused-image / fraud-ring detection (ADR-0004).

Optional and side-effect-free unless ``DATABASE_URL`` is set *and*
``psycopg`` + ``pgvector`` are importable. When a claim's image matches an
already-indexed image from a **different user** within a small distance, the
image is almost certainly reused (stock photo, forwarded, or recycled across
claims) — surfaced as the ``non_original_image`` risk flag, which the rule layer
turns into ``valid_image=false`` + ``manual_review_required``.

Design:
- One image == one row, keyed by the sha256 of the original file (idempotent
  re-indexing; byte-identical cross-user reuse collapses to one "original" row).
- The pipeline indexes the run's images once (sequentially) up-front, then each
  worker thread issues **read-only** nearest-neighbour queries (its own
  connection), so there is no write race during the concurrent pass.
- The embedding backend (``embeddings.py``) defines the metric + dimension:
  perceptual-hash → L2 over {0,1} bits (Hamming), CLIP → cosine.

CLI (via the ``code/dedup.py`` entry point)::

    python code/dedup.py index    # index sample + test images
    python code/dedup.py report   # list cross-user near-duplicate images
    python code/dedup.py reset    # drop the table
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path

from . import datasets, embeddings

_TABLE = "image_vectors"


def enabled() -> bool:
    """True iff a DB is configured and the optional client libs are importable."""
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        import psycopg  # noqa: F401
        import pgvector  # noqa: F401
        return True
    except Exception:
        return False


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _distance_threshold() -> tuple[str, float]:
    """(SQL operator, max distance) for the active embedding backend."""
    if embeddings.metric() == "cosine":
        return "<=>", float(os.environ.get("ORCH_DEDUP_COSINE", "0.08"))
    # L2 over {0,1} bit vectors: distance^2 == #differing bits (Hamming).
    hamming = int(os.environ.get("ORCH_DEDUP_HAMMING", "8"))
    return "<->", float(hamming) ** 0.5


class VectorStore:
    """Thin pgvector wrapper. Connections are per-thread (psycopg conns are not
    shareable across threads)."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ["DATABASE_URL"]
        self.dim = embeddings.dim()
        self.backend = embeddings.backend()
        self._local = threading.local()

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            import psycopg
            from pgvector.psycopg import register_vector

            conn = psycopg.connect(self.dsn, autocommit=True)
            register_vector(conn)
            self._local.conn = conn
        return conn

    # -- schema ---------------------------------------------------------------
    def ensure_schema(self) -> None:
        conn = self._conn()
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                sha256     text PRIMARY KEY,
                user_id    text NOT NULL,
                image_id   text NOT NULL,
                image_path text NOT NULL,
                backend    text NOT NULL,
                embedding  vector({self.dim}) NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        # Guard against mixing embedding backends (different dim/metric) in one table.
        row = conn.execute(
            f"SELECT backend FROM {_TABLE} WHERE backend <> %s LIMIT 1", (self.backend,)
        ).fetchone()
        if row:
            raise RuntimeError(
                f"{_TABLE} already holds '{row[0]}' embeddings but the active backend is "
                f"'{self.backend}'. Run `vectorstore.py reset` before switching backends."
            )

    # -- indexing -------------------------------------------------------------
    def index_image(self, *, user_id: str, rel_path: str) -> None:
        path = datasets.resolve_image(rel_path)
        sha = _file_sha(path)
        vec = embeddings.embed_image(path)
        self._conn().execute(
            f"""INSERT INTO {_TABLE} (sha256, user_id, image_id, image_path, backend, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (sha256) DO NOTHING""",
            (sha, user_id, datasets.image_id(rel_path), rel_path, self.backend, vec),
        )

    def index_claims(self, claims: list[dict]) -> int:
        """Index every image referenced by ``claims`` (sequential, idempotent)."""
        n = 0
        for c in claims:
            for rel in datasets.parse_image_paths(c["image_paths"]):
                try:
                    self.index_image(user_id=c.get("user_id", ""), rel_path=rel)
                    n += 1
                except Exception as exc:  # a bad image must not abort the run
                    print(f"[vectorstore] skip {rel}: {exc}", file=sys.stderr)
        return n

    # -- query ----------------------------------------------------------------
    def flag_reused(self, claim_row: dict) -> set[str]:
        """Read-only: return {'non_original_image'} if any of this claim's images
        matches an indexed image from a *different* user within threshold."""
        op, thr = _distance_threshold()
        user_id = claim_row.get("user_id", "")
        conn = self._conn()
        for rel in datasets.parse_image_paths(claim_row["image_paths"]):
            try:
                vec = embeddings.embed_image(datasets.resolve_image(rel))
            except Exception:
                continue
            row = conn.execute(
                f"""SELECT user_id, embedding {op} %s AS dist
                    FROM {_TABLE}
                    WHERE user_id <> %s
                    ORDER BY embedding {op} %s
                    LIMIT 1""",
                (vec, user_id, vec),
            ).fetchone()
            if row is not None and row[1] is not None and float(row[1]) <= thr:
                return {"non_original_image"}
        return set()

    def report(self) -> list[tuple]:
        """Cross-user near-duplicate image pairs (for the CLI / fraud review)."""
        op, thr = _distance_threshold()
        conn = self._conn()
        return conn.execute(
            f"""SELECT a.user_id, a.image_path, b.user_id, b.image_path,
                       a.embedding {op} b.embedding AS dist
                FROM {_TABLE} a JOIN {_TABLE} b ON a.sha256 < b.sha256
                WHERE a.user_id <> b.user_id AND a.embedding {op} b.embedding <= %s
                ORDER BY dist""",
            (thr,),
        ).fetchall()

    def reset(self) -> None:
        self._conn().execute(f"DROP TABLE IF EXISTS {_TABLE}")


# --- CLI ----------------------------------------------------------------------
def cli(argv: list[str]) -> int:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set — nothing to do.", file=sys.stderr)
        return 2
    if not enabled():
        print("psycopg / pgvector not installed (pip install -r code/requirements-infra.txt).",
              file=sys.stderr)
        return 2

    cmd = argv[0] if argv else "index"
    store = VectorStore()

    if cmd == "reset":
        store.reset()
        print("dropped image_vectors")
        return 0

    store.ensure_schema()

    if cmd == "index":
        from .config import DATASET_DIR
        total = 0
        for name in ("sample_claims.csv", "claims.csv"):
            p = DATASET_DIR / name
            if p.exists():
                total += store.index_claims(datasets.load_claims(p))
        print(f"indexed {total} images ({store.backend}, dim={store.dim})")
        return 0

    if cmd == "report":
        pairs = store.report()
        if not pairs:
            print("no cross-user near-duplicate images found")
            return 0
        print(f"{len(pairs)} cross-user near-duplicate pair(s):")
        for ua, pa, ub, pb, dist in pairs:
            print(f"  {ua}:{pa}  ==  {ub}:{pb}   (dist={float(dist):.3f})")
        return 0

    print(f"unknown command: {cmd!r} (use: index | report | reset)", file=sys.stderr)
    return 2


if __name__ == "__main__":  # `python -m orchestrate.vectorstore ...`
    raise SystemExit(cli(sys.argv[1:]))
