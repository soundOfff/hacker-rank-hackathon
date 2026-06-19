#!/usr/bin/env python3
"""AGENTS.md conversation logger — the single mechanism for §2/§5 logging.

This is *agent infrastructure*, deliberately kept out of the evaluable ``code/``
solution. Any coding agent working in this repo (Claude Code, Codex, Gemini,
Cursor, sub-agents, worktrees...) should append its entries through this helper
so the format stays exactly as AGENTS.md §5 prescribes.

Design constraints (AGENTS.md §2 & §7):
- Log lives OUTSIDE the repo, in the user's home dir, so it survives branch
  switches / worktrees / ``git clean``:
    macOS / Linux : ``$HOME/hackerrank_orchestrate/log.txt``
    Windows       : ``%USERPROFILE%\\hackerrank_orchestrate\\log.txt``
- Append-only. UTF-8, ``\\n`` line endings on every platform.
- Never log secrets: API keys / tokens / bearer headers are redacted on write.
- No third-party dependencies; standard library only.

CLI (all writes go through ``_redact`` first)::

    python scripts/agent_log.py status
    python scripts/agent_log.py agreement --agent "Claude Code" --language py
    python scripts/agent_log.py session-start --agent "Claude Code" --language py
    python scripts/agent_log.py turn --title "..." \\
        --prompt-file PROMPT.txt --summary-file SUMMARY.txt \\
        --action "edited code/orchestrate/llm.py" --action "ran tests"

``--prompt-file`` / ``--summary-file`` are preferred over inline flags so prompt
text (which may be long or contain quotes) never has to be shell-escaped.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- Challenge config (AGENTS.md §4) ------------------------------------------
# 2026-06-20 11:00 IST.  IST is a fixed UTC+5:30 offset (no DST).
IST = timezone(timedelta(hours=5, minutes=30))
CHALLENGE_END = datetime(2026, 6, 20, 11, 0, tzinfo=IST)


# --- Paths --------------------------------------------------------------------
def log_path() -> Path:
    """Resolve the platform log path from the home dir (never hardcoded)."""
    return Path.home() / "hackerrank_orchestrate" / "log.txt"


def repo_root() -> str:
    """Absolute path of the repo root (git toplevel, else this file's parent)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return str(Path(__file__).resolve().parents[1])


def git_branch() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# --- Time ---------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def time_remaining(at: datetime | None = None) -> str:
    at = at or datetime.now(timezone.utc)
    delta = CHALLENGE_END - at
    if delta.total_seconds() <= 0:
        return "challenge ended"
    total_min = int(delta.total_seconds() // 60)
    d, rem = divmod(total_min, 60 * 24)
    h, m = divmod(rem, 60)
    return f"{d}d {h}h {m}m"


# --- Redaction (AGENTS.md §2 / §5.4) ------------------------------------------
# BEST-EFFORT: catches the common secret shapes below, but is NOT a guarantee.
# The real control is never pasting raw secrets into a prompt in the first place.
# Each entry is (pattern, replacement): standalone-secret patterns redact the
# whole match; keyword/value patterns keep a readable prefix and redact the value.
_KEYWORDS = (
    r"api[_-]?key|secret[_-]?key|access[_-]?key|client[_-]?secret|"
    r"token|secret|password|passwd|authorization|auth"
)
_REDACTIONS = [
    # Multi-line PEM private key blocks (§5.4 "private keys").
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----", re.DOTALL),
     "[REDACTED]"),
    # Provider API keys / tokens (standalone — redact wherever they appear).
    (re.compile(r"sk-or-v1-[A-Za-z0-9\-_]{8,}"), "[REDACTED]"),            # OpenRouter
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{8,}"), "[REDACTED]"),             # Anthropic
    (re.compile(r"sk-proj-[A-Za-z0-9\-_]{12,}"), "[REDACTED]"),           # OpenAI project
    (re.compile(r"sk-[A-Za-z0-9\-_]{20,}"), "[REDACTED]"),                # OpenAI classic
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED]"),            # GitHub
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),          # Slack bot/user
    (re.compile(r"xapp-[0-9]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),          # Slack app-level
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),                  # AWS access key id
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED]"),            # Google API key
    # Auth-scheme header values (multi-token credential after the scheme word).
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-_\.=+/]{8,}"), r"\1 [REDACTED]"),
    # Cookie headers — redact the whole value to end of line (§5.4 "session cookies").
    (re.compile(r"(?i)\b(set-cookie|cookie)(\s*[:=]\s*).+"), r"\1\2[REDACTED]"),
    # keyword: value / keyword=value, incl. JSON "keyword": "value" (quote may sit
    # between the keyword and the separator). Redacts the value, not the keyword.
    (re.compile(r'(?i)(["\']?\b(?:' + _KEYWORDS + r')\b["\']?)(\s*[:=]\s*)(["\']?)([^\s"\',}]+)'),
     r"\1\2\3[REDACTED]"),
]


def _redact(text: str) -> str:
    out = text
    for pat, repl in _REDACTIONS:
        out = pat.sub(repl, out)
    return out


# --- Append -------------------------------------------------------------------
def _append(block: str) -> None:
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = _redact(block.rstrip("\n")) + "\n\n"
    # Force \n line endings even on Windows (AGENTS.md §7).
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)


def is_onboarded(root: str | None = None) -> bool:
    root = root or repo_root()
    p = log_path()
    if not p.exists():
        return False
    needle = f"AGREEMENT RECORDED: {root}"
    return needle in p.read_text(encoding="utf-8")


# --- Entry builders (AGENTS.md §3.4 / §5.1 / §5.2) ----------------------------
def record_agreement(agent: str, language: str, root: str | None = None,
                     note: str | None = None) -> None:
    root = root or repo_root()
    lines = [
        f"## [{now_iso()}] ONBOARDING COMPLETE",
        "",
        f"AGREEMENT RECORDED: {root}",
        f"Agent: {agent}",
        f"Language: {language}",
        f"System Time: {now_iso()}",
        f"Time Remaining: {time_remaining()}",
    ]
    if note:
        lines.append(f"Note: {note}")
    _append("\n".join(lines))


def session_start(agent: str, language: str, parent_agent: str = "none",
                  worktree: str = "main", root: str | None = None) -> None:
    root = root or repo_root()
    lines = [
        f"## [{now_iso()}] SESSION START",
        "",
        f"Agent: {agent}",
        f"Repo Root: {root}",
        f"Branch: {git_branch()}",
        f"Worktree: {worktree}",
        f"Parent Agent: {parent_agent}",
        f"Language: {language}",
        f"Time Remaining: {time_remaining()}",
    ]
    _append("\n".join(lines))


def log_turn(title: str, user_prompt: str, summary: str, actions: list[str],
             agent: str, parent_agent: str = "none", worktree: str = "main",
             root: str | None = None) -> None:
    root = root or repo_root()
    title = title[:80]
    action_lines = "\n".join(f"* {a}" for a in actions) if actions else "* (none)"
    lines = [
        f"## [{now_iso()}] {title}",
        "",
        "User Prompt (verbatim, secrets redacted):",
        user_prompt.strip(),
        "",
        "Agent Response Summary:",
        summary.strip(),
        "",
        "Actions:",
        action_lines,
        "",
        "Context:",
        f"tool={agent}",
        f"branch={git_branch()}",
        f"repo_root={root}",
        f"worktree={worktree}",
        f"parent_agent={parent_agent}",
    ]
    _append("\n".join(lines))


# --- CLI ----------------------------------------------------------------------
def _read_arg(inline: str | None, path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return inline or ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AGENTS.md conversation logger.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="print log path, onboarding state, time left")

    common = dict()
    for name in ("agreement", "session-start"):
        sp = sub.add_parser(name)
        sp.add_argument("--agent", default="unknown")
        sp.add_argument("--language", default="py")
        if name == "agreement":
            sp.add_argument("--note", default=None)
        if name == "session-start":
            sp.add_argument("--parent-agent", default="none")
            sp.add_argument("--worktree", default="main")

    sp = sub.add_parser("turn")
    sp.add_argument("--title", required=True)
    sp.add_argument("--prompt", default=None)
    sp.add_argument("--prompt-file", default=None)
    sp.add_argument("--summary", default=None)
    sp.add_argument("--summary-file", default=None)
    sp.add_argument("--action", action="append", default=[], dest="actions")
    sp.add_argument("--agent", default="unknown")
    sp.add_argument("--parent-agent", default="none")
    sp.add_argument("--worktree", default="main")

    args = ap.parse_args(argv)

    if args.cmd == "status":
        print(f"log_path     : {log_path()}")
        print(f"exists       : {log_path().exists()}")
        print(f"repo_root    : {repo_root()}")
        print(f"onboarded    : {is_onboarded()}")
        print(f"time_remaining: {time_remaining()}")
        return 0

    if args.cmd == "agreement":
        record_agreement(args.agent, args.language, note=args.note)
        print(f"Recorded agreement -> {log_path()}")
        return 0

    if args.cmd == "session-start":
        session_start(args.agent, args.language,
                      parent_agent=args.parent_agent, worktree=args.worktree)
        print(f"Recorded session start -> {log_path()}")
        return 0

    if args.cmd == "turn":
        prompt = _read_arg(args.prompt, args.prompt_file)
        summary = _read_arg(args.summary, args.summary_file)
        log_turn(args.title, prompt, summary, args.actions, args.agent,
                 parent_agent=args.parent_agent, worktree=args.worktree)
        print(f"Recorded turn -> {log_path()}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
