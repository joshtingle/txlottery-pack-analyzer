#!/usr/bin/env python
"""PreToolUse gate for agent spawns: blocks any Agent/Task spawn whose
description lacks a model tier tag like [haiku], or whose explicit model
override contradicts that tag.  Exit 2 blocks the call and feeds stderr
back to the model so it can fix the spawn and retry."""
import json
import re
import sys

TIERS = ("haiku", "sonnet", "opus", "fable")


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


def main() -> int:
    text = read_stdin_text()
    try:
        d = json.loads(text)
    except Exception:
        try:
            d = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text))
        except Exception:
            return 0
    if d.get("tool_name") not in ("Task", "Agent"):
        return 0
    ti = d.get("tool_input") or {}
    desc = str(ti.get("description") or "")
    m = re.search(r"\[(%s)\]" % "|".join(TIERS), desc, re.I)
    if not m:
        sys.stderr.write(
            "Spawn blocked by tier gate: the agent description must carry its "
            "model tier in brackets, e.g. 'Backfill event table [haiku]'. "
            "Got: %r. Add the tag matching the model this agent runs on, "
            "then retry the spawn." % desc
        )
        return 2
    tag = m.group(1).lower()
    model = str(ti.get("model") or "").lower()
    if model and tag not in model:
        sys.stderr.write(
            "Spawn blocked by tier gate: description tag [%s] contradicts the "
            "model override %r. Fix whichever is wrong so the running-agents "
            "view stays truthful, then retry." % (tag, model)
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
