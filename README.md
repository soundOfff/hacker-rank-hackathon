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
<img width="5885" height="8192" alt="Claims Evidence-2026-06-19-193121" src="https://github.com/user-attachments/assets/bbd78788-28a5-4410-bf16-67ce03716fc5" />


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

## Setup

### Prerequisites

- Python 3.10+ (or your language of choice)
- An OpenRouter API key (get one at [openrouter.ai/keys](https://openrouter.ai/keys))
- Docker (optional, for full stack with Redis + Postgres/pgvector)

### Quick Setup

```bash
# Install Python dependencies
pip install -U -r code/requirements.txt

# Configure your API key
cp code/.env.example code/.env
# Edit code/.env and add: OPENROUTER_API_KEY=sk-or-v1-...

# Or export directly
export OPENROUTER_API_KEY=sk-or-v1-...
```

### Optional Infrastructure (Redis cache + pgvector dedup)

For shared caching and cross-user image deduplication:

```bash
# Install infrastructure dependencies
pip install -U -r code/requirements-infra.txt

# Or use Docker to run the full stack (no local Python setup needed)
echo "OPENROUTER_API_KEY=sk-or-v1-..." >> .env
docker compose run --rm app
```

### Run the Solution

```bash
# Generate final predictions: dataset/claims.csv → output.csv
python code/main.py

# Quick test on a few rows
python code/main.py --limit 3

# Run evaluation on sample data
python code/evaluation/main.py

# Run deterministic tests (no API key needed)
python code/tests/test_rules.py && python code/tests/test_router.py
```

---

## Approach Overview

The implemented solution uses a **three-stage pipeline** that balances cost, accuracy, and defensibility:

### Stage 1: Claim Extraction (Text-only, Haiku 4.5)

- Normalizes multilingual chat transcripts (Hindi/Hinglish, Spanish, Chinese) to canonical English claim intent
- Extracts claimed object parts and issue types
- Flags instruction/manipulation text in the conversation as untrusted data

### Stage 2: Visual Verification (Single-routed Vision Model)

- **Images are the source of truth** for all visual judgments
- Structured output: `issue_type`, `object_part`, `claim_status`, `evidence_standard_met`, `valid_image`, `severity`, `supporting_image_ids`, visual risk flags
- **Single-route model selection** (cost-first default):
  - **Sonnet 4.6** on every claim (~$0.91 for 44 test rows)
  - Optional router can escalate hard cases to **Opus 4.8** before any vision call
  - Accuracy-first mode: `--mode forced --model anthropic/claude-opus-4.8` (~$1.56)
- No double-pay: every claim pays for exactly one Stage-2 call

### Stage 3: Deterministic Rule Layer (No API calls)

- **100% reproducible** business logic implemented in Python
- Enforces field consistency (`evidence_standard_met=false ⟺ claim_status=not_enough_information`)
- Derives `user_history_risk` and `manual_review_required` flags mechanically
- User history context never overrides clear visual evidence
- Validated against all 20 labeled samples with no API key (`code/tests/test_rules.py`)

### Adversarial Handling

- **Prompt injection** (in chat or image): flagged `text_instruction_present`, treated as untrusted, never moves verdict
- **Non-original images** (watermarks, stock photos): flagged `non_original_image` → `valid_image=false`
- **Exaggeration**: `severity` reflects actual visible damage, not claimed magnitude
- **Cross-user image reuse** (optional, pgvector): images used by multiple users flagged for fraud detection

### Key Design Decisions

See [`docs/adr/`](./docs/adr/) for detailed rationale:

- **[ADR-0001](./docs/adr/0001-two-stage-pipeline-with-rule-layer.md)**: Two-stage model pipeline + deterministic rule layer
- **[ADR-0002](./docs/adr/0002-openrouter-provider.md)**: OpenRouter as provider (OpenAI-compatible API, model-agnostic)
- **[ADR-0003](./docs/adr/0003-single-route-stage2.md)**: Single-route Stage-2 (no confidence-escalation double-pay)
- **[ADR-0004](./docs/adr/0004-pgvector-image-dedup.md)**: pgvector for reused-image detection across users

### Cost & Reproducibility

- **44-row test set cost**: ~$0.91 (Sonnet-all, shipped default) | ~$1.09 (router armed) | ~$1.56 (Opus-all)
- Structured outputs pin every field to allowed enums
- System prompt + evidence requirements are prompt-cached
- Images downscaled to 1568px max dimension
- Responses cached by input hash (filesystem or Redis)
- Full operational analysis in [`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md)

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
