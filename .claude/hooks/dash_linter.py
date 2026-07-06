#!/usr/bin/env python
"""PostToolUse writing linter for .md files: flags dash punctuation (em dash,
en dash, spaced double hyphen) in content just written or edited.  Warn-level:
the write already happened; exit 2 feeds the finding back to the model so it
cleans up in place.  CLI flags like --flag do not match (the double-hyphen
pattern requires surrounding spaces)."""
import json
import re
import sys

PATTERNS = (
    ("em dash", re.compile(r"—")),
    ("en dash", re.compile(r"–")),
    ("spaced double hyphen", re.compile(r"(?<=\S) -- (?=\S)")),
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
    if d.get("tool_name") not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return 0
    ti = d.get("tool_input") or {}
    path = str(ti.get("file_path") or "")
    if not path.lower().endswith(".md"):
        return 0
    text = str(ti.get("content") or ti.get("new_string") or "")
    findings = [(label, len(rx.findall(text))) for label, rx in PATTERNS]
    findings = [(label, n) for label, n in findings if n]
    if not findings:
        return 0
    detail = ", ".join("%s x%d" % (label, n) for label, n in findings)
    sys.stderr.write(
        "Writing rule: dash punctuation found in %s (%s). The rule bans dashes "
        "as sentence punctuation; restructure with a colon, parentheses, commas, "
        "or two sentences. If these are legacy instances carried through an edit "
        "of an old file, clean them opportunistically; never add new ones."
        % (path, detail)
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
