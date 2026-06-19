#!/usr/bin/env python3
"""Export the Claude Code conversation(s) for this repo into one readable,
secret-redacted ``chat_transcript.md`` for the HackerRank submission.

This is *agent infrastructure* (like ``agent_log.py``), kept out of the
evaluable ``code/`` solution. It reads the local Claude Code session logs
(``~/.claude/projects/<slug>/*.jsonl``), merges every session for this repo in
chronological order, and renders a human-readable Markdown transcript:

- user prompts (slash-commands labelled), assistant prose, and a compact
  one-line summary of every tool call (what file was edited / command run);
- ``tool_result`` bodies are condensed (outputs, not authored content) and
  base64 image data is dropped;
- secrets (API keys / tokens / key=value assignments) are redacted on write;
- ``<system-reminder>`` / ``<local-command-*>`` harness noise is stripped.

Usage::

    python scripts/export_transcript.py                 # -> ./chat_transcript.md
    python scripts/export_transcript.py -o OUT.md
    python scripts/export_transcript.py --include-thinking   # keep reasoning blocks

The output file is git-ignored (it is a regenerable submission artifact).
No third-party dependencies; standard library only.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from pathlib import Path

# --- Secret redaction (mirrors scripts/agent_log.py) --------------------------
_SECRET_PATTERNS = [
    (re.compile(r"sk-or-v1-[A-Za-z0-9\-_]{8,}"), "[REDACTED-OPENROUTER-KEY]"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{8,}"), "[REDACTED-ANTHROPIC-KEY]"),
    (re.compile(r"sk-proj-[A-Za-z0-9\-_]{12,}"), "[REDACTED-OPENAI-KEY]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED-GH-TOKEN]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED-AWS-KEY]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
     "[REDACTED-JWT]"),
]
# KEY=value / KEY: value for sensitive names, unless the value is a placeholder.
_KV_SECRET = re.compile(
    r"((?:[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_KEY))\s*[=:]\s*)"
    r"(['\"]?)([^\s'\"]+)",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"(\.\.\.|your[-_]|<|xxx|replace|example|changeme|\$\{)", re.IGNORECASE)

# Long base64-ish blobs (e.g. inline images) -> dropped.
_BASE64_BLOB = re.compile(r"(?:data:[^;]+;base64,)?[A-Za-z0-9+/]{200,}={0,2}")
_SYS_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_LOCAL_CMD = re.compile(r"</?local-command-[^>]*>")


def redact(text: str) -> str:
    if not text:
        return text
    text = _BASE64_BLOB.sub("[base64-data-omitted]", text)
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)

    def _kv(m: re.Match) -> str:
        if _PLACEHOLDER.search(m.group(3)):
            return m.group(0)  # placeholder, keep as-is
        return f"{m.group(1)}{m.group(2)}[REDACTED]"

    return _KV_SECRET.sub(_kv, text)


def strip_noise(text: str) -> str:
    text = _SYS_REMINDER.sub("", text)
    text = _LOCAL_CMD.sub("", text)
    return text.strip()


def truncate(text: str, n: int) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[:n].rstrip() + f" … [+{len(text) - n} chars]"


# --- Tool-call one-liners -----------------------------------------------------
def summarize_tool_use(name: str, inp: dict) -> str:
    inp = inp or {}
    if name == "Bash":
        desc = inp.get("description") or (inp.get("command", "").splitlines() or [""])[0]
        return f"`Bash` — {truncate(redact(desc), 160)}"
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return f"`{name}` — {inp.get('file_path', inp.get('notebook_path', '?'))}"
    if name in ("Grep", "Glob"):
        return f"`{name}` — {inp.get('pattern', '?')}"
    if name == "Task" or name == "Agent":
        return f"`{name}` — {truncate(redact(inp.get('description', '')), 120)}"
    if name == "TodoWrite":
        return "`TodoWrite` — (task list update)"
    # Generic: show a couple of short scalar params.
    parts = []
    for k, v in inp.items():
        if isinstance(v, (str, int, float, bool)) and len(str(v)) < 80:
            parts.append(f"{k}={truncate(redact(str(v)), 60)}")
        if len(parts) >= 2:
            break
    return f"`{name}`" + (f" — {', '.join(parts)}" if parts else "")


def render_tool_result(content) -> str:
    if isinstance(content, list):
        chunks = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "image":
                    chunks.append("[image omitted]")
                elif b.get("type") == "text":
                    chunks.append(b.get("text", ""))
            elif isinstance(b, str):
                chunks.append(b)
        content = "\n".join(chunks)
    if not isinstance(content, str):
        content = str(content)
    content = strip_noise(redact(content))
    return truncate(content, 280)


# --- Event extraction ---------------------------------------------------------
def iter_events(project_dir: Path):
    for f in glob.glob(str(project_dir / "*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") in ("user", "assistant") and e.get("timestamp"):
                    yield e


def render(events, include_thinking: bool) -> str:
    out: list[str] = []
    cur_session = None
    for e in events:
        sid = e.get("sessionId", "")
        if sid != cur_session:
            cur_session = sid
            ts = e.get("timestamp", "")[:19].replace("T", " ")
            out.append(f"\n---\n\n### Session `{sid[:8]}` — starting {ts} UTC\n")

        role = e["type"]
        side = " (sub-agent)" if e.get("isSidechain") else ""
        msg = e.get("message", {})
        content = msg.get("content")

        if role == "user":
            # String content: slash-command or raw prompt or harness noise.
            if isinstance(content, str):
                cmd = re.search(r"<command-name>\s*(/?[^<]+?)\s*</command-name>", content)
                args = re.search(r"<command-args>(.*?)</command-args>", content, re.DOTALL)
                if cmd:
                    label = cmd.group(1).strip()
                    a = strip_noise(redact(args.group(1))) if args else ""
                    out.append(f"\n**User** — invoked `{label}` {('`' + truncate(a, 100) + '`') if a else ''}".rstrip())
                else:
                    txt = strip_noise(redact(content))
                    if txt:
                        out.append(f"\n**User:**\n\n{truncate(txt, 4000)}")
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        txt = strip_noise(redact(b.get("text", "")))
                        if txt:
                            out.append(f"\n**User:**\n\n{truncate(txt, 4000)}")
                    elif b.get("type") == "tool_result":
                        res = render_tool_result(b.get("content"))
                        if res:
                            out.append(f"  ⎿ _result:_ {res}")

        else:  # assistant
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    txt = strip_noise(redact(b.get("text", "")))
                    if txt:
                        out.append(f"\n**Assistant{side}:**\n\n{txt}")
                elif bt == "thinking" and include_thinking:
                    th = truncate(strip_noise(redact(b.get("thinking", ""))), 800)
                    if th:
                        out.append(f"\n> 🧠 _(reasoning)_ {th}")
                elif bt == "tool_use":
                    out.append(f"\n  → {summarize_tool_use(b.get('name', '?'), b.get('input'))}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="chat_transcript.md")
    ap.add_argument("--include-thinking", action="store_true",
                    help="include (truncated) assistant reasoning blocks")
    ap.add_argument("--project-dir", default=None,
                    help="override the ~/.claude/projects/<slug> directory")
    args = ap.parse_args()

    if args.project_dir:
        project_dir = Path(args.project_dir)
    else:
        repo = Path(__file__).resolve().parent.parent
        slug = str(repo).replace("/", "-")
        project_dir = Path.home() / ".claude" / "projects" / slug

    if not project_dir.exists():
        raise SystemExit(f"No Claude Code logs found at {project_dir}")

    events = sorted(iter_events(project_dir), key=lambda e: e.get("timestamp", ""))
    sessions = sorted({e.get("sessionId", "") for e in events})
    span = (events[0]["timestamp"][:19], events[-1]["timestamp"][:19]) if events else ("", "")

    header = [
        "# Chat Transcript — HackerRank Orchestrate (Multi-Modal Evidence Review)",
        "",
        "Development conversation(s) for this submission, exported from Claude Code "
        "session logs. Secrets are redacted; base64 image data and harness noise are stripped.",
        "",
        f"- **Sessions:** {len(sessions)}  |  **Messages:** {len(events)}",
        f"- **Span (UTC):** {span[0].replace('T', ' ')} → {span[1].replace('T', ' ')}",
        "- **Note:** any development done in other tools (e.g. Cursor) is not captured here.",
        "",
        "Tool calls are summarized as one-liners (`→ Tool — target`); tool outputs are "
        "condensed. Use `--include-thinking` to regenerate with assistant reasoning.",
    ]
    body = render(events, args.include_thinking)
    out_text = "\n".join(header) + "\n" + body + "\n"

    Path(args.output).write_text(out_text, encoding="utf-8")
    print(f"Wrote {args.output}: {len(events)} messages across {len(sessions)} session(s), "
          f"{len(out_text):,} chars.")


if __name__ == "__main__":
    main()
