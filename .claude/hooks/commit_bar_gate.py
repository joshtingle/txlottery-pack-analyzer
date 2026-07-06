#!/usr/bin/env python
"""PreToolUse gate on Bash: intercepts git commit and enforces two
independent markers.  Bar marker: a fresh green stamp from run_bar.py,
dormant until the project creates .claude/bar.json.  Adjudication marker:
commits staging files under the project's adjudicated risk paths
(.claude/risk-paths.json categories with adjudicate true, e.g. order
execution or risk code; legacy .claude/money-paths.json honored as a
fallback) require a fresh .adjudication-pass stamped by /verify-up on an
adjudicator-tier CONFIRM; dormant without either config.  Both make
"never lands without verification" enforcement rather than prose."""
import json
import os
import re
import subprocess
import sys
import time

MAX_AGE_SECONDS = 1800


def clean_prefix(p: str) -> str:
    """Project-relative declared prefix: forward slashes, a single leading
    './' or '/' removed as a prefix (never character-stripped, so
    dot-prefixed paths like '.claude/hooks/' survive), lowercased."""
    p = p.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    elif p.startswith("/"):
        p = p[1:]
    return p.lower()


def adjudicated_prefixes(root: str):
    """Path prefixes whose commits require adjudication: risk-paths.json
    categories flagged adjudicate true, else the legacy money-paths.json
    list (all of which is treated as adjudicated)."""
    cfg = os.path.join(root, ".claude", "risk-paths.json")
    if os.path.isfile(cfg):
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                cats = json.load(f).get("categories") or {}
            prefixes = []
            for spec in cats.values():
                if spec.get("adjudicate"):
                    prefixes.extend(
                        clean_prefix(p) for p in (spec.get("paths") or [])
                    )
            return prefixes
        except (OSError, ValueError, AttributeError):
            return []
    legacy = os.path.join(root, ".claude", "money-paths.json")
    if not os.path.isfile(legacy):
        return []
    try:
        with open(legacy, "r", encoding="utf-8") as f:
            return [clean_prefix(p) for p in (json.load(f).get("paths") or [])]
    except (OSError, ValueError):
        return []


def adjudicated_path_check(root: str) -> int:
    prefixes = adjudicated_prefixes(root)
    if not prefixes:
        return 0
    try:
        out = subprocess.run(
            ["git", "-C", root, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=8,
        ).stdout
    except Exception:
        return 0
    staged = [
        l.strip().replace("\\", "/").lower() for l in out.splitlines() if l.strip()
    ]
    hits = [s for s in staged if any(s.startswith(p) for p in prefixes)]
    if not hits:
        return 0
    marker = os.path.join(root, ".adjudication-pass")
    fresh = (
        os.path.isfile(marker)
        and (time.time() - os.path.getmtime(marker)) <= MAX_AGE_SECONDS
    )
    confirmed = False
    if fresh:
        try:
            with open(marker, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            first_line = lines[0].strip() if lines else ""
            first_token = first_line.split()[0].upper() if first_line.split() else ""
            confirmed = first_token == "CONFIRM"
        except OSError:
            confirmed = False
    if fresh and confirmed:
        return 0
    sys.stderr.write(
        "Commit blocked: staged changes touch adjudicated paths (%s). "
        "Money-touching or irreversible work lands only after an "
        "adjudicator-tier CONFIRM via /verify-up, which stamps "
        ".adjudication-pass at the project root. Run /verify-up with the "
        "adjudicator against the pre-registered bar, then retry the commit."
        % ", ".join(hits[:5])
    )
    return 2


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
    if d.get("tool_name") != "Bash":
        return 0
    cmd = str((d.get("tool_input") or {}).get("command") or "")
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd):
        return 0
    root = str(d.get("cwd") or os.getcwd())
    rc = adjudicated_path_check(root)
    if rc:
        return rc
    if not os.path.isfile(os.path.join(root, ".claude", "bar.json")):
        return 0
    marker = os.path.join(root, ".claude", "last-bar-pass")
    hint = (
        " Run the bar first: python .claude/hooks/run_bar.py "
        "(it stamps the marker only on a green run)."
    )
    if not os.path.isfile(marker):
        sys.stderr.write("Commit blocked: no green-bar marker exists." + hint)
        return 2
    age = time.time() - os.path.getmtime(marker)
    if age > MAX_AGE_SECONDS:
        sys.stderr.write(
            "Commit blocked: green-bar marker is %d minutes old (limit %d)."
            % (age // 60, MAX_AGE_SECONDS // 60) + hint
        )
        return 2
    try:
        with open(marker, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        content = ""
    if "PASS" not in content:
        sys.stderr.write("Commit blocked: bar marker does not record a pass." + hint)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
