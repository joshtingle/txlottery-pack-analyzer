#!/usr/bin/env python
"""PreToolUse gate on Write, Edit, and MultiEdit: touching a file under a
declared risk path requires a fresh judgment-tier route stamp.  The commit
gate catches an unadjudicated landing; this gate catches the misroute at
generation time, before the first line is produced, so a misrouted attempt
costs nothing instead of a full wasted unit.  Declarations live in
.claude/risk-paths.json (categories of path prefixes, each with an
adjudicate flag read by the commit gate); .claude/money-paths.json is
honored as a legacy fallback.  /route stamps .current-route with the tier
when it classifies a unit.  Dormant when no declaration file exists.
Exit 2 blocks the edit and tells the model to run /route first."""
import json
import os
import posixpath
import re
import sys
import time

MAX_AGE_SECONDS = 4 * 3600
GATED_TOOLS = ("Write", "Edit", "MultiEdit")


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


def load_categories(root: str):
    """Returns {category: [prefix, ...]} for every declared category, or
    an empty dict when no declaration file exists (gate dormant)."""
    cfg = os.path.join(root, ".claude", "risk-paths.json")
    if os.path.isfile(cfg):
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                cats = json.load(f).get("categories") or {}
            out = {}
            for name, spec in cats.items():
                prefixes = [clean_prefix(p) for p in (spec.get("paths") or [])]
                if prefixes:
                    out[name] = prefixes
            return out
        except (OSError, ValueError, AttributeError):
            return {}
    legacy = os.path.join(root, ".claude", "money-paths.json")
    if os.path.isfile(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                prefixes = [clean_prefix(p) for p in (json.load(f).get("paths") or [])]
            return {"money": prefixes} if prefixes else {}
        except (OSError, ValueError):
            return {}
    return {}


def relative_to_root(path: str, root: str) -> str:
    """Project-relative form of path, normalized (dot and dot-dot segments
    collapsed), lowercased, forward slashes, or an empty string when the
    path is not under the project root."""
    norm = posixpath.normpath(path.replace("\\", "/")).lower()
    root_norm = posixpath.normpath(root.replace("\\", "/")).lower().rstrip("/") + "/"
    if norm.startswith(root_norm):
        rel = norm[len(root_norm):]
    elif re.match(r"^([a-z]:)?/", norm):
        return ""
    else:
        rel = norm
    rel = posixpath.normpath(rel)
    if rel == "." or rel == ".." or rel.startswith("../"):
        return ""
    return rel


def main() -> int:
    text = read_stdin_text()
    try:
        d = json.loads(text)
    except Exception:
        try:
            d = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text))
        except Exception:
            return 0
    if d.get("tool_name") not in GATED_TOOLS:
        return 0
    path = str((d.get("tool_input") or {}).get("file_path") or "")
    if not path:
        return 0
    root = str(d.get("cwd") or os.getcwd())
    categories = load_categories(root)
    if not categories:
        return 0
    rel = relative_to_root(path, root)
    if not rel:
        return 0
    hit = None
    for name, prefixes in categories.items():
        if any(rel.startswith(p) for p in prefixes):
            hit = name
            break
    if hit is None:
        return 0
    marker = os.path.join(root, ".current-route")
    fresh = (
        os.path.isfile(marker)
        and (time.time() - os.path.getmtime(marker)) <= MAX_AGE_SECONDS
    )
    tier = ""
    if fresh:
        try:
            with open(marker, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            first_line = lines[0] if lines else ""
        except OSError:
            first_line = ""
        tier = first_line.split("|")[0].strip().lower()
    if fresh and tier in ("judgment", "adjudicator"):
        return 0
    sys.stderr.write(
        "Edit blocked by the risk gate: '%s' is under a declared %s risk "
        "path (.claude/risk-paths.json) and no fresh judgment-tier route "
        "stamp exists. Work on declared risk paths routes to judgment or "
        "above, never lower and never inline. Run /route (it classifies "
        "this category as judgment and stamps .current-route), register "
        "the bar via /bar, then retry this edit." % (rel, hit)
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
