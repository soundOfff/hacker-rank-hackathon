"""Runtime configuration: paths, models, pricing, and tunables.

All settings have sensible defaults; the entry points expose the important ones
as CLI flags.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv  # optional convenience
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:  # pragma: no cover - dotenv is optional
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
CACHE_DIR = REPO_ROOT / ".cache" / "responses"

# --- Provider: OpenRouter (OpenAI-compatible) ---------------------------------
# Models are served through OpenRouter so the pipeline is provider-portable; the
# transport is the OpenAI SDK pointed at OpenRouter's base URL (see ADR-0002).
OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
)
# Optional attribution headers OpenRouter uses for app rankings (harmless if unset).
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "")
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "hackerrank-orchestrate")

# --- Models (OpenRouter slugs; see CONTEXT.md / ADR-0001 / ADR-0002) ----------
# Overridable via env so the run stays reproducible by default but retargetable.
STAGE1_MODEL = os.environ.get("ORCH_STAGE1_MODEL", "anthropic/claude-haiku-4.5")          # cheap text-only claim extraction
STAGE2_DEFAULT_MODEL = os.environ.get("ORCH_STAGE2_MODEL", "anthropic/claude-sonnet-4.6")  # vision workhorse
STAGE2_ESCALATION_MODEL = os.environ.get("ORCH_STAGE2_ESCALATION_MODEL", "anthropic/claude-opus-4.8")  # escalation for low-confidence rows

# Per-1M-token list pricing (USD), for the operational analysis only. Keyed by
# the OpenRouter slug; an unknown (env-overridden) model simply costs $0 in the
# estimate rather than erroring.
PRICING = {
    "anthropic/claude-haiku-4.5": {"input": 1.00, "output": 5.00},
    "anthropic/claude-sonnet-4.6": {"input": 3.00, "output": 15.00},
    "anthropic/claude-opus-4.8": {"input": 5.00, "output": 25.00},
}
# Prompt-cache multipliers relative to base input price (for cost estimates).
CACHE_READ_MULT = 0.10
CACHE_WRITE_MULT = 1.25


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var (1/true/yes/on); fall back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # Image preprocessing
    image_max_edge: int = 1280
    image_jpeg_quality: int = 85

    # Concurrency / robustness
    max_workers: int = 6
    max_retries: int = 4

    # Stage-2 reasoning controls (Haiku stage-1 takes neither)
    stage2_effort: str = "medium"   # low | medium | high | max (Sonnet/Opus only)
    stage2_thinking: bool = True     # adaptive thinking on Stage 2

    # Token ceilings
    stage1_max_tokens: int = 1024
    stage2_max_tokens: int = 3000

    # Single-route policy (ADR-0003). A claim is routed to the (pricier)
    # escalation model *up-front* — before any vision call — when a cheap
    # pre-Stage-2 signal marks it hard/adversarial; otherwise it runs the default
    # model. Either way each claim pays for exactly ONE Stage-2 call. This
    # replaces the old confidence-escalation path, which always ran the default
    # model and *then* re-ran the escalation model on top (two paid Stage-2 calls
    # on every escalated row — see ADR-0003).
    #
    # SHIPPED DEFAULT = cost-first (all triggers off → Sonnet on every claim).
    # The evaluation showed text/history routing is *dominated* on the sample —
    # the only rows Opus uniquely fixes are image-hard, not text-hard, so these
    # signals can't catch them (ADR-0003). The router stays armed and one flag
    # away: flip a trigger on (or set the matching ORCH_ROUTE_* env) to escalate,
    # and the planned CLIP image-vs-claim signal (vectorstore, ADR-0004) is the
    # trigger that finally makes routing Pareto-beat both extremes.
    route_on_instruction_text: bool = _env_bool("ORCH_ROUTE_ON_INSTRUCTION_TEXT", False)
    route_on_multi_part: bool = _env_bool("ORCH_ROUTE_ON_MULTI_PART", False)
    route_on_history_risk: bool = _env_bool("ORCH_ROUTE_ON_HISTORY_RISK", False)

    use_cache: bool = True


SETTINGS = Settings()


def require_api_key() -> str:
    # Accept OPENROUTER_API_KEY (primary) or a generic OPENAI_API_KEY for users
    # who already point the OpenAI SDK at OpenRouter via env.
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit(
            "OPENROUTER_API_KEY is not set. Add it to your environment or to a "
            ".env file (see code/.env.example)."
        )
    return key
