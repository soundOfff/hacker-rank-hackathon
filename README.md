# HackerRank Orchestrate

Starter repository for the **HackerRank Orchestrate** 24-hour hackathon.

Build a system that verifies visual evidence for damage claims across three object types: **cars**, **laptops**, and **packages**.

Your system will receive claim conversations, one or more submitted images, user claim history, and minimum evidence requirements. It must decide whether the submitted images support the claim, contradict it, or do not provide enough information.

Read [`problem_statement.md`](./problem_statement.md) for the full task spec, input/output schema, and allowed values.

---

## Contents

1. [Repository layout](#repository-layout)
2. [What you need to build](#what-you-need-to-build)
3. [Where your code goes](#where-your-code-goes)
4. [Quickstart](#quickstart)
5. [Evaluation](#evaluation)
6. [Chat transcript logging](#chat-transcript-logging)
7. [Submission](#submission)
8. [Judge interview](#judge-interview)

---

## Repository layout

```text
.
├── AGENTS.md                         # Rules for AI coding tools + transcript logging
├── problem_statement.md              # Full task description and I/O schema
├── README.md                         # You are here
├── CONTEXT.md                        # Shared domain language and glossary
├── docs/adr/                         # Architecture Decision Records
│   ├── 0001-two-stage-pipeline-with-rule-layer.md
│   ├── 0002-openrouter-provider.md
│   ├── 0003-single-route-stage2.md
│   └── 0004-pgvector-image-dedup.md
├── code/                             # Build your solution here
│   ├── main.py                       # Terminal entry point
│   ├── dedup.py                      # pgvector reused-image detection
│   ├── README.md                     # Implementation documentation
│   ├── orchestrate/                  # Core pipeline modules
│   ├── evaluation/                   # Evaluation framework
│   └── tests/                        # Unit tests (no API key needed)
├── dataset/
│   ├── sample_claims.csv             # Inputs + expected outputs for development
│   ├── claims.csv                    # Inputs only; run your system on these rows
│   ├── user_history.csv              # Historical claim counts and risk context
│   ├── evidence_requirements.csv     # Minimum image evidence requirements
│   └── images/
│       ├── sample/                   # Images referenced by sample_claims.csv
│       └── test/                     # Images referenced by claims.csv
├── Dockerfile                        # Container for the solution
├── docker-compose.yml                # Full stack: app + Redis + Postgres/pgvector
└── output.csv                        # Final predictions (generated)
```

---

## Solution Architecture

The implemented solution uses a **three-stage pipeline** with single-route model selection for cost efficiency:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INPUT SOURCES                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  claims.csv          user_history.csv     evidence_requirements.csv         │
│  (user_id, images,   (historical flags)   (minimum standards per object)    │
│   transcript, obj)                                                          │
│                                                                             │
│  dataset/images/{sample,test}/                                              │
│  (img_001.jpg, img_002.png, ...)                                            │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     OPTIONAL: pgvector Deduplication                        │
│                          (if DATABASE_URL set)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Index all images with pHash or CLIP embeddings                          │
│  • Flag images reused across different users → non_original_image          │
│  • Enables fraud ring detection                                            │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STAGE 1: Claim Extraction                                │
│                         (Haiku 4.5, text-only)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Input:  Multilingual chat transcript                                      │
│  Output: Canonical claim intent (JSON)                                     │
│    • claimed_parts: list[str]       (e.g., ["front_bumper"])               │
│    • claimed_issues: list[str]      (e.g., ["dent", "scratch"])            │
│    • claim_summary: str             (normalized English)                   │
│    • is_multi_part: bool            (escalation signal)                    │
│    • instruction_text_in_chat: bool (adversarial signal)                   │
│                                                                             │
│  Handles: Hindi/Hinglish, Spanish, Chinese pinyin, mixed scripts           │
│  Detects: Prompt injection attempts in chat ("approve immediately")        │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ROUTER: Model Selection                               │
│                   (Deterministic, cost-first default)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  Picks exactly ONE Stage-2 model before any vision call:                   │
│                                                                             │
│  Default path (shipped):                                                   │
│    Sonnet 4.6  ← majority of claims (70% acc, ~$0.91/44 claims)            │
│                                                                             │
│  Escalation triggers (configurable via ORCH_ROUTE_ON_*):                   │
│    Opus 4.8    ← if instruction_text_in_chat                               │
│              OR if is_multi_part                                            │
│              OR if user_history_risk                                        │
│                                                                             │
│  Accuracy-first mode (optional):                                           │
│    Opus 4.8    ← every claim (80% acc, ~$1.56/44 claims)                   │
│                                                                             │
│  Result: No double-pay (old: Sonnet then Opus = ~$2.09)                    │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  STAGE 2: Visual Verification                               │
│              (Single-routed: Sonnet 4.6 or Opus 4.8)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  Input:  Images (base64), Stage-1 intent, evidence requirements            │
│  Output: Structured JSON with strict enums                                 │
│    • claim_status: supported | contradicted | not_enough_information       │
│    • claim_status_justification: str                                       │
│    • evidence_standard_met: bool                                           │
│    • evidence_standard_met_reason: str                                     │
│    • issue_type: dent|scratch|crack|glass_shatter|...                      │
│    • object_part: front_bumper|screen|seal|...                             │
│    • severity: none|low|medium|high|unknown                                │
│    • valid_image: bool                                                     │
│    • risk_flags: list[str]  (claim_mismatch, possible_manipulation, ...)  │
│    • supporting_image_ids: list[str]  (img_001, img_002, ...)             │
│    • confidence: low|medium|high                                           │
│                                                                             │
│  Features:                                                                 │
│    • Images downscaled (max 1568px) for cost efficiency                    │
│    • Prompt caching: system + requirements table = stable prefix           │
│    • Response caching: identical inputs → cached result (no API call)      │
│    • Cache backend: filesystem (default) or Redis (if REDIS_URL set)       │
│                                                                             │
│  Adversarial handling:                                                     │
│    • Text in images ("APPROVE THIS") → possible_manipulation flag          │
│    • Watermarks/stock photos → non_original_image flag                     │
│    • Transcript instructions ignored (marked untrusted)                    │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   STAGE 3: Deterministic Rule Layer                         │
│                       (Pure Python, no API calls)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  Enforces invariants that models shouldn't decide:                         │
│                                                                             │
│  1. Evidence → Status coupling:                                            │
│     evidence_standard_met=false ⟹ claim_status=not_enough_information    │
│                                 ⟹ severity=unknown                        │
│                                                                             │
│  2. Severity anchoring:                                                    │
│     issue_type=none ⟹ severity=none                                       │
│                                                                             │
│  3. Image validity:                                                        │
│     non_original_image flag ⟹ valid_image=false                           │
│                                                                             │
│  4. Flag consolidation:                                                    │
│     • Merge chat flags (text_instruction_present)                          │
│     • Merge pgvector flags (non_original_image from dedup)                 │
│     • Add user_history_risk (from user_history.csv)                        │
│     • Deduplicate and canonically order all flags                          │
│                                                                             │
│  5. Manual review trigger:                                                 │
│     manual_review_required ⟸ user_history_risk                           │
│                            OR substantive evidence flags                    │
│                            OR processing error (fallback row)               │
│                                                                             │
│  6. Enum normalization:                                                    │
│     • Validate all outputs against allowed_values.py                       │
│     • Convert bools to "true"/"false" strings                              │
│     • Format supporting_image_ids / risk_flags                             │
│                                                                             │
│  Tested: 100% of 20 labeled samples via tests/test_rules.py (no API key)   │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          OUTPUT: output.csv                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  14 columns (4 input passthrough + 10 predicted):                          │
│    user_id, image_paths, user_claim, claim_object,                         │
│    evidence_standard_met, evidence_standard_met_reason,                    │
│    risk_flags, issue_type, object_part,                                    │
│    claim_status, claim_status_justification,                               │
│    supporting_image_ids, valid_image, severity                             │
│                                                                             │
│  Guarantees:                                                               │
│    • One row per input claim (errors → fallback row)                       │
│    • All enums from allowed_values.py                                      │
│    • Exact schema from problem_statement.md                                │
│    • Deterministic for same inputs (via response cache)                    │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌───────────────────────────────┐
                    │  Concurrency & Infrastructure │
                    ├───────────────────────────────┤
                    │  • ThreadPoolExecutor         │
                    │  • Shared response cache:     │
                    │    - Filesystem (default)     │
                    │    - Redis (via REDIS_URL)    │
                    │  • Optional pgvector store    │
                    │  • Docker Compose stack       │
                    └───────────────────────────────┘
```

### Key Design Decisions

See [`docs/adr/`](./docs/adr/) for detailed rationale:

- **[ADR-0001](./docs/adr/0001-two-stage-pipeline-with-rule-layer.md)**: Two-stage model pipeline + deterministic rule layer
- **[ADR-0002](./docs/adr/0002-openrouter-provider.md)**: OpenRouter as provider (OpenAI-compatible API)
- **[ADR-0003](./docs/adr/0003-single-route-stage2.md)**: Single-route Stage-2 selection (no double-pay)
- **[ADR-0004](./docs/adr/0004-pgvector-image-dedup.md)**: pgvector for reused-image detection

---

## What you need to build

A system that, for each row in `dataset/claims.csv`, produces one row in `output.csv`.

Input fields:

| Column | Meaning |
|---|---|
| `user_id` | User submitting the claim; use this to look up `dataset/user_history.csv` |
| `image_paths` | One or more submitted image paths, separated by semicolons |
| `user_claim` | Chat transcript describing the issue |
| `claim_object` | `car`, `laptop`, or `package` |

Required output fields:

| Column | Meaning |
|---|---|
| `evidence_standard_met` | Whether the image set is sufficient to evaluate the claim |
| `evidence_standard_met_reason` | Short reason for the evidence decision |
| `risk_flags` | Semicolon-separated risk flags, or `none` |
| `issue_type` | Visible issue type |
| `object_part` | Relevant object part |
| `claim_status` | `supported`, `contradicted`, or `not_enough_information` |
| `claim_status_justification` | Concise explanation grounded in the image evidence |
| `supporting_image_ids` | Image IDs supporting the decision, or `none` |
| `valid_image` | Whether the image set is usable for automated review |
| `severity` | `none`, `low`, `medium`, `high`, or `unknown` |

Hard requirements:

- Must read the provided CSV files and local images.
- Must produce `output.csv` with the exact schema in `problem_statement.md`.
- Must include an evaluation workflow
- Must avoid hardcoded test labels or file-specific answers.

Beyond that you are free to bring your own approach: VLMs, LLMs, structured prompting, rule layers, batching, caching, evaluation pipelines, model comparison, or anything else.

---

## Where your code goes

All of your work belongs in [`code/`](./code/). The repo ships with empty starter files that you can grow into your full solution.

Suggested conventions:

- Put your main runnable solution in `code/main.py`, or document your own entry point clearly.
- Put evaluation code under `code/evaluation/` or an `evaluation/` folder included in your final `code.zip`.
- Write final predictions to `output.csv`.

---

## Quickstart

Clone this repository:

```bash
git clone git@github.com:interviewstreet/hackerrank-orchestrate-june26.git
cd hackerrank-orchestrate-june26
```

You are free to use any language or runtime. Python, JavaScript, and TypeScript are all reasonable choices.

---

## Evaluation

The evaluation report should include:

- metrics on `dataset/sample_claims.csv`
- at least two strategies, prompts, or model configurations compared
- the final strategy used for `output.csv`
- operational analysis covering model calls, token usage, image usage, approximate cost, runtime, and TPM/RPM considerations

---

## Chat transcript logging

This repo ships with an `AGENTS.md` that modern AI coding tools may read. It instructs the tool to append conversation turns to a shared log file:

| Platform | Path |
|---|---|
| macOS / Linux | `$HOME/hackerrank_orchestrate/log.txt` |
| Windows | `%USERPROFILE%\hackerrank_orchestrate\log.txt` |

You will upload this log as your chat transcript at submission time. The chat transcript means your conversation with the AI coding tool you used to build the system. It is not the runtime logs, reasoning trace, or conversation history produced by the claim-verification agent you are building.

If you use multiple AI tools, include the relevant conversation logs from all of them in the same transcript file. Separate each tool's section with a clear divider and label it with the tool name.

Never paste secrets into the chat. If secrets are needed, use environment variables.

---

## Submission

Submit the following files as instructed by HackerRank:

1. **Code zip**: zip your runnable solution, README, prompts/configs, and evaluation folder. Exclude virtualenvs, `node_modules`, build artifacts, and unnecessary generated files.
2. **Predictions CSV**: your final `output.csv` for all rows in `dataset/claims.csv`.
3. **Chat transcript**: the `log.txt` from the path in [Chat transcript logging](#chat-transcript-logging).

Before submitting, confirm:

- `output.csv` has one row per row in `dataset/claims.csv`.
- `output.csv` has the exact required columns in the exact required order.
- Your evaluation files are included in `code.zip`.

---

## Judge interview

After submission, the AI Judge may ask about your approach, implementation decisions, model usage, evaluation strategy, and how you used AI while building the solution.

Be prepared to explain your solution in detail.
