#!/usr/bin/env python
"""SessionStart hook: reads the adjudicator agent's pinned model and injects
a one-line check into session context.  The session compares that pin against
the newest top-tier model it knows to be available (from its own system
context, which names current model families) and, when a stronger tier
exists, asks the owner before anything repoints.  The hook supplies the
guaranteed reminder; the model supplies the comparison; the owner supplies
the decision."""
import os
import re
import sys


def main() -> None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    path = os.path.join(root, ".claude", "agents", "adjudicator.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            head = f.read(2000)
    except OSError:
        return
    m = re.search(r"^model:\s*(\S+)", head, re.M)
    if not m:
        return
    pinned = m.group(1)
    sys.stdout.write(
        "Routing map check (session start): the adjudicator agent is pinned to "
        "model '%s' (.claude/agents/adjudicator.md). Compare that against the "
        "newest top-tier Claude model you know to be generally available. If a "
        "strictly stronger tier exists, ask the owner before any high-stakes "
        "work: \"I currently have %s set as the highest model and adjudicator, "
        "but I see that {stronger model} is available. Do you want to update?\" "
        "On a yes, follow the repoint procedure in docs/MODEL_ROUTING.md and "
        "run the eval set. If '%s' is still the strongest available, say "
        "nothing about this check." % (pinned, pinned, pinned)
    )


if __name__ == "__main__":
    main()
