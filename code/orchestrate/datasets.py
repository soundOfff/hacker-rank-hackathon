"""Loaders for the four dataset CSVs and image-path helpers."""

from __future__ import annotations

import csv
from pathlib import Path

from .allowed_values import OUTPUT_COLUMNS
from .config import DATASET_DIR


def load_claims(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_user_history(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["user_id"]] = row
    return rows


def load_evidence_requirements(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def format_requirements(reqs: list[dict]) -> str:
    """Render the full evidence-requirements table for the (cached) system prompt.

    The whole table goes in the system prompt so the prefix stays byte-identical
    across all claims and prompt-caching applies.
    """
    lines = []
    for r in reqs:
        lines.append(
            f"- [{r['claim_object']} | {r['applies_to']}] {r['minimum_image_evidence']}"
        )
    return "\n".join(lines)


def parse_image_paths(image_paths: str) -> list[str]:
    """Split the semicolon-separated image_paths field into relative paths."""
    return [p.strip() for p in image_paths.split(";") if p.strip()]


def image_id(rel_path: str) -> str:
    """Image id = filename without extension (e.g. img_1)."""
    return Path(rel_path).stem


def resolve_image(rel_path: str) -> Path:
    """image_paths are relative to the dataset/ directory."""
    return DATASET_DIR / rel_path


def write_output_csv(path: Path, rows: list[dict]) -> None:
    """Write rows in the exact required column order, fully quoted (matches the
    sample files' QUOTE_ALL style)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=OUTPUT_COLUMNS, quoting=csv.QUOTE_ALL, extrasaction="ignore"
        )
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in OUTPUT_COLUMNS})
