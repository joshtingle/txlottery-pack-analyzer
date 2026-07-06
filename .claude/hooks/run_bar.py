#!/usr/bin/env python
"""Runs the project's default bar (.claude/bar.json {"command": ...}) and
stamps .claude/last-bar-pass on green.  A red run removes any stale marker
and exits with the bar command's own exit code, so this script's exit code
IS the bar verdict.  commit_bar_gate.py trusts only this marker."""
import json
import os
import subprocess
import sys
import time


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    cfg_path = os.path.join(root, ".claude", "bar.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cmd = cfg["command"]
    except (OSError, KeyError, ValueError) as e:
        sys.stderr.write("run_bar: unreadable %s (%s)\n" % (cfg_path, e))
        return 1
    result = subprocess.run(cmd, shell=True, cwd=root)
    marker = os.path.join(root, ".claude", "last-bar-pass")
    if result.returncode == 0:
        with open(marker, "w", encoding="utf-8") as f:
            f.write("PASS %s\ncommand: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), cmd))
        print("run_bar: PASS, marker stamped")
        return 0
    try:
        os.remove(marker)
    except OSError:
        pass
    sys.stderr.write("run_bar: RED (exit %d), marker cleared\n" % result.returncode)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
