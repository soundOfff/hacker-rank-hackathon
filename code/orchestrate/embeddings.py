"""Image embeddings for the vector store (ADR-0004).

Two backends, selected by ``ORCH_EMBED_BACKEND``:

- ``phash`` (default): a dependency-light perceptual hash (difference hash /
  dHash, Pillow only) rendered as a 64-dim {0,1} vector. Near-identical for the
  same or lightly-edited/re-encoded image, which is exactly the signal for
  *reused / non-original* images — and it needs no torch, so the Docker image
  stays small.
- ``clip``: semantic CLIP embeddings (``clip-ViT-B-32`` via
  ``sentence-transformers``), 512-dim, L2-normalized. Heavier, but catches
  same-scene / different-shot similarity. Install the optional dep and set
  ``ORCH_EMBED_BACKEND=clip``.

The active backend's dimensionality (:func:`dim`) defines the pgvector column, so
pick one backend per database.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image

_PHASH_SIDE = 8  # dHash grid -> 8x8 = 64 bits


def backend() -> str:
    return os.environ.get("ORCH_EMBED_BACKEND", "phash").strip().lower()


def dim() -> int:
    return 512 if backend() == "clip" else _PHASH_SIDE * _PHASH_SIDE


def metric() -> str:
    """Distance metric the store should query with for this backend."""
    return "cosine" if backend() == "clip" else "l2"


def _dhash_vector(path: Path) -> list[float]:
    """dHash: compare horizontally-adjacent pixels of a 9x8 grayscale thumbnail."""
    with Image.open(path) as im:
        small = im.convert("L").resize((_PHASH_SIDE + 1, _PHASH_SIDE), Image.LANCZOS)
        px = list(small.getdata())
    w = _PHASH_SIDE + 1
    bits: list[float] = []
    for r in range(_PHASH_SIDE):
        row = px[r * w:(r + 1) * w]
        for c in range(_PHASH_SIDE):
            bits.append(1.0 if row[c] < row[c + 1] else 0.0)
    return bits


@lru_cache(maxsize=1)
def _clip_model():
    from sentence_transformers import SentenceTransformer  # optional dep

    return SentenceTransformer("clip-ViT-B-32")


def _clip_vector(path: Path) -> list[float]:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        vec = _clip_model().encode(rgb, normalize_embeddings=True)
    return [float(x) for x in vec]


def embed_image(path: str | Path) -> list[float]:
    """Embed one image file into a vector for the active backend."""
    path = Path(path)
    if backend() == "clip":
        return _clip_vector(path)
    return _dhash_vector(path)
