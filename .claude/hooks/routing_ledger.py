#!/usr/bin/env python
"""SubagentStart/SubagentStop ledger: appends one JSONL line per event to
<project>/.claude/routing-ledger.jsonl, with the model tier parsed from the
agent description or type.  The /routing-review skill pairs start and stop
events by agent_id to compute durations and climb patterns.  Append-only and
best-effort: a ledger failure must never block work."""
import json
import os
import re
import sys
import time

TIER_RX = re.compile(r"\[(haiku|sonnet|opus|fable)\]", re.I)

# fallback when the hook payload omits the description (observed 2026-07-06):
# bench agents pin their model in frontmatter, so agent_type implies the tier
AGENT_TIERS = {
    "mechanical-executor": "haiku",
    "implementer": "sonnet",
    "qa-reviewer": "sonnet",
    "judgment-designer": "opus",
    "adjudicator": "fable",
}


def read_stdin_text() -> str:
    raw = sys.stdin.buffer.read()
    for enc in ("utf-8-sig", "utf-8", "utf-16-le", "utf-16"):
        try:
            t = raw.decode(enc)
            if "{" in t:
                return t
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def main() -> None:
    text = read_stdin_text()
    try:
        d = json.loads(text)
    except Exception:
        try:
            d = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text))
        except Exception:
            return
    event = d.get("hook_event_name") or ""
    if event not in ("SubagentStart", "SubagentStop"):
        return
    desc = str(d.get("description") or d.get("agent_description") or "")
    atype = str(d.get("agent_type") or "")
    m = TIER_RX.search(desc) or TIER_RX.search(atype)
    tier = m.group(1).lower() if m else AGENT_TIERS.get(atype)
    line = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event,
        "session_id": d.get("session_id"),
        "agent_id": d.get("agent_id"),
        "agent_type": atype or None,
        "description": desc or None,
        "tier": tier,
    }
    root = str(d.get("cwd") or os.getcwd())
    path = os.path.join(root, ".claude", "routing-ledger.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
