#!/usr/bin/env python
"""PreToolUse gate on Write: creating a new code file requires a fresh bar
marker (.current-bar at the project root, gitignored), stamped by /bar when
it records the bar in TODO.md.  Enforces pre-registration for exactly the work size that needs it:
new code files mean a non-trivial unit; plain edits stay ungated so the
trivial-work floor survives.  Markdown, config, and .claude paths are exempt.
Exit 2 blocks the write and tells the model to run /bar first."""
import json
import os
import re
import sys
import time

MAX_AGE_SECONDS = 4 * 3600
CODE_EXTS = (
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".sql",
    ".sh", ".ps1", ".go", ".rs", ".java", ".cs", ".rb", ".php",
)


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
    if d.get("tool_name") != "Write":
        return 0
    path = str((d.get("tool_input") or {}).get("file_path") or "")
    norm = path.replace("\\", "/").lower()
    if not norm.endswith(CODE_EXTS):
        return 0
    if "/.claude/" in norm or "/node_modules/" in norm:
        return 0
    root = str(d.get("cwd") or os.getcwd())
    marker = os.path.join(root, ".current-bar")
    fresh = (
        os.path.isfile(marker)
        and (time.time() - os.path.getmtime(marker)) <= MAX_AGE_SECONDS
    )
    if fresh:
        return 0
    sys.stderr.write(
        "Write blocked by the bar gate: creating a new code file is a "
        "non-trivial unit of work and no fresh bar is registered. Run /bar "
        "first: record the checkable bar in TODO.md and stamp .current-bar "
        "at the project root with the bar text, then retry this write. "
        "(A bar stated in the request still gets recorded; the record is "
        "what /verify-up checks against.)"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
