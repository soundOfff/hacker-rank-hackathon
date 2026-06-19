---
status: accepted
---

# pgvector image store for reused-image / fraud-ring detection

An **optional** Postgres + `pgvector` store (`orchestrate/vectorstore.py`) that
fingerprints every submitted image and flags an image as reused when it matches
an indexed image from a **different user** within a small distance. A reused
image surfaces as the `non_original_image` risk flag, which the existing rule
layer already turns into `valid_image=false` + `manual_review_required`
(ADR-0001) — so no output schema changes, just a new cheap source of evidence.

## Context

Image authenticity (`non_original_image`, `valid_image`) is otherwise left to the
Stage-2 VLM, which sees each claim in isolation and cannot know that *the same
photo was already submitted by someone else*. Cross-claim image reuse is the
strongest cheap signal for stock images, recycled "evidence", and fraud rings,
and it scales: with a big CSV you want to compare each image against a growing
corpus of everything seen so far, not re-reason per claim.

## Decision

- **Store**: one row per image keyed by the sha256 of the original file
  (idempotent indexing); columns `(sha256, user_id, image_id, image_path,
  backend, embedding vector(N))`. `CREATE EXTENSION vector` + a single table.
- **Embeddings** (`orchestrate/embeddings.py`, swappable):
  - default **`phash`** — a Pillow-only difference hash as a 64-dim {0,1} vector;
    near-identical for the same / lightly-edited image, L2 distance² = #differing
    bits (Hamming). No torch, so the Docker image stays small. This is the right
    signal for *reuse*, which is exact-ish, not semantic.
  - optional **`clip`** — `clip-ViT-B-32`, 512-dim, cosine — for same-scene
    similarity. Needs `sentence-transformers`; enable with `ORCH_EMBED_BACKEND=clip`.
- **Detection**: index the run's images once up-front (sequential — no write
  race), then each worker thread runs a read-only nearest-neighbour query
  (its own connection). A match with a different `user_id` within
  `ORCH_DEDUP_HAMMING` (default 8) / `ORCH_DEDUP_COSINE` (default 0.08) →
  `non_original_image`.
- **Strictly optional**: active only when `DATABASE_URL` is set and
  `psycopg`/`pgvector` import; otherwise the pipeline behaves exactly as before.
  Brought up automatically by `docker compose` (Postgres `pgvector/pgvector:pg16`).

## Considered options

- **Ask the VLM to judge authenticity per image (status quo).** Cheap to keep,
  but blind to cross-claim reuse — the signal that actually catches rings.
- **Exact sha/byte match only.** Catches identical files but not re-encoded /
  resized / lightly-edited reuse; a perceptual vector does both, and `pgvector`
  makes "nearest within ε over millions of rows" an indexed query.
- **pgvector store (chosen).** One small table + extension; the same index also
  powers the planned image-vs-claim routing signal (ADR-0003).

## Consequences

- New, deterministic source of `non_original_image` that improves with volume
  (more history → more reuse caught), threaded into `rules.finalize` via
  `extra_visual_flags` and unit-tested without a DB (`tests/test_extra_flags.py`).
- First-seen image is treated as the "original"; reuse is attributed to later
  submitters. Indexing order therefore matters — acceptable for a review signal
  that gates manual review rather than auto-deciding.
- Inline detection is best-effort and never fails a claim. The `code/dedup.py`
  CLI (`index` / `report` / `reset`) gives a clean offline pass and a cross-user
  near-duplicate report for fraud review.
- Same embedding backend must be used for a given table (dimension/metric are
  fixed at creation); `ensure_schema` guards against mixing.
- A natural next step (ADR-0003): feed the image-vs-claim-object distance from
  this store into the Stage-2 router as the cheap pre-vision signal that the
  text/history triggers lack.
