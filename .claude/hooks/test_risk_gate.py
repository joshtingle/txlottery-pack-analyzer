#!/usr/bin/env python
"""Red tests for risk_gate.py and the adjudicated-path clause of
commit_bar_gate.py.  Builds throwaway sandboxes, feeds each hook simulated
PreToolUse payloads over stdin, and asserts exit codes: 2 where the gate
must block, 0 where it must stay silent (including fail-open on malformed
payloads and dormancy without a declaration file).  Exit 0 means every
case passed."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HOOKS = os.path.dirname(os.path.abspath(__file__))
RISK_GATE = os.path.join(HOOKS, "risk_gate.py")
COMMIT_GATE = os.path.join(HOOKS, "commit_bar_gate.py")

RESULTS = []


def run_hook(hook, payload_text):
    p = subprocess.run(
        [sys.executable, hook],
        input=payload_text.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )
    return p.returncode


def payload(tool, root, file_path=None, command=None):
    tool_input = {}
    if file_path is not None:
        tool_input["file_path"] = file_path
    if command is not None:
        tool_input["command"] = command
    return json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": root})


def check(name, got, want):
    ok = got == want
    RESULTS.append((name, ok))
    print("%s %s (exit %s, expected %s)" % ("PASS" if ok else "FAIL", name, got, want))


def make_sandbox(config=None, legacy=None):
    root = tempfile.mkdtemp(prefix="riskgate-")
    os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
    if config is not None:
        with open(os.path.join(root, ".claude", "risk-paths.json"), "w", encoding="utf-8") as f:
            json.dump(config, f)
    if legacy is not None:
        with open(os.path.join(root, ".claude", "money-paths.json"), "w", encoding="utf-8") as f:
            json.dump(legacy, f)
    return root


def stamp_route(root, text):
    with open(os.path.join(root, ".current-route"), "w", encoding="utf-8") as f:
        f.write(text)


CONFIG = {
    "categories": {
        "money": {"paths": ["trading/execution/", "gate/"], "adjudicate": True},
        "schema": {"paths": ["migrations/"], "adjudicate": False},
    }
}


def main():
    sandboxes = []

    # Sandbox A: categorized declarations.
    a = make_sandbox(config=CONFIG)
    sandboxes.append(a)
    risky = os.path.join(a, "trading", "execution", "order.py")
    safe = os.path.join(a, "app", "ui", "button.jsx")

    check("risky Edit, no route stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", a, file_path=risky)), 2)
    check("risky Write, no route stamp, blocks",
          run_hook(RISK_GATE, payload("Write", a, file_path=risky)), 2)
    stamp_route(a, "judgment | risk gate unit | 2026-07-06")
    check("risky Edit, fresh judgment stamp, passes",
          run_hook(RISK_GATE, payload("Edit", a, file_path=risky)), 0)
    check("risky MultiEdit, fresh judgment stamp, passes",
          run_hook(RISK_GATE, payload("MultiEdit", a, file_path=risky)), 0)
    stamp_route(a, "standard | some other unit | 2026-07-06")
    check("risky Edit, standard-tier stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", a, file_path=risky)), 2)
    stamp_route(a, "standard | update adjudicator docs wording | 2026-07-06")
    check("risky Edit, sub-judgment stamp with trigger words in one-liner, blocks",
          run_hook(RISK_GATE, payload("Edit", a, file_path=risky)), 2)
    stamp_route(a, "mechanical | sweep judgment-signal table refs | 2026-07-06")
    check("schema Edit, mechanical stamp naming judgment in one-liner, blocks",
          run_hook(RISK_GATE, payload("Edit", a, file_path=os.path.join(a, "migrations", "0002.sql"))), 2)
    os.remove(os.path.join(a, ".current-route"))
    dotted = a + "/trading/./execution/order.py"
    check("risky Edit via /./ path form, no stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", a, file_path=dotted)), 2)
    traversal = a + "/x/../trading/execution/order.py"
    check("risky Edit via dot-dot traversal form, no stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", a, file_path=traversal)), 2)
    stamp_route(a, "judgment | risk gate unit | 2026-07-06")
    stamp_route(a, "judgment | risk gate unit | 2026-07-06")
    old = time.time() - 5 * 3600
    os.utime(os.path.join(a, ".current-route"), (old, old))
    check("risky Edit, stale judgment stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", a, file_path=risky)), 2)
    check("non-risk Edit, no stamp needed, passes",
          run_hook(RISK_GATE, payload("Edit", a, file_path=safe)), 0)
    check("schema-category Edit, no stamp, blocks (all categories gate generation)",
          run_hook(RISK_GATE, payload("Edit", a, file_path=os.path.join(a, "migrations", "0001.sql"))), 2)
    check("malformed payload, fail-open",
          run_hook(RISK_GATE, "{'tool_name': broken"), 0)
    check("Bash tool payload, ignored",
          run_hook(RISK_GATE, payload("Bash", a, command="ls")), 0)

    # Sandbox E: dot-prefixed declaration must survive prefix cleaning.
    e = make_sandbox(config={
        "categories": {"internal": {"paths": [".claude/hooks/"], "adjudicate": False}}
    })
    sandboxes.append(e)
    check("dot-prefixed declared path enforces, no stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", e, file_path=os.path.join(e, ".claude", "hooks", "foo.py"))), 2)

    # Sandbox G: leading-slash declaration is normalized, not a silent no-op.
    g = make_sandbox(config={
        "categories": {"money": {"paths": ["/trading/execution/"], "adjudicate": True}}
    })
    sandboxes.append(g)
    check("leading-slash declared path enforces, no stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", g, file_path=os.path.join(g, "trading", "execution", "order.py"))), 2)

    # Sandbox B: no declaration files, gate dormant.
    b = make_sandbox()
    sandboxes.append(b)
    check("no declarations, dormant, passes",
          run_hook(RISK_GATE, payload("Edit", b, file_path=os.path.join(b, "trading", "execution", "x.py"))), 0)

    # Sandbox C: legacy money-paths.json only.
    c = make_sandbox(legacy={"paths": ["trading/execution/"]})
    sandboxes.append(c)
    c_risky = os.path.join(c, "trading", "execution", "order.py")
    check("legacy declaration, risky Edit, no stamp, blocks",
          run_hook(RISK_GATE, payload("Edit", c, file_path=c_risky)), 2)
    stamp_route(c, "judgment | legacy unit | 2026-07-06")
    check("legacy declaration, judgment stamp, passes",
          run_hook(RISK_GATE, payload("Edit", c, file_path=c_risky)), 0)

    # Commit gate: sandbox A with a staged adjudicated file.
    def git(root, *args):
        subprocess.run(["git", "-C", root] + list(args), capture_output=True, timeout=30)

    git(a, "init", "-q")
    os.makedirs(os.path.dirname(risky), exist_ok=True)
    with open(risky, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    git(a, "add", "trading/execution/order.py")
    commit_payload = payload("Bash", a, command="git commit -m 'test'")
    check("commit staging adjudicated path, no stamp, blocks",
          run_hook(COMMIT_GATE, commit_payload), 2)
    with open(os.path.join(a, ".adjudication-pass"), "w", encoding="utf-8") as f:
        f.write("CONFIRM risk gate unit 2026-07-06")
    check("commit staging adjudicated path, fresh CONFIRM, passes",
          run_hook(COMMIT_GATE, commit_payload), 0)
    with open(os.path.join(a, ".adjudication-pass"), "w", encoding="utf-8") as f:
        f.write("did not CONFIRM the unit; see rejection")
    check("commit gate, stamp not beginning with CONFIRM, blocks",
          run_hook(COMMIT_GATE, commit_payload), 2)
    with open(os.path.join(a, ".adjudication-pass"), "w", encoding="utf-8") as f:
        f.write("CONFIRMATION PENDING: adjudicator not yet run")
    check("commit gate, first token CONFIRMATION not CONFIRM, blocks",
          run_hook(COMMIT_GATE, commit_payload), 2)

    # Sandbox F: case-mismatched declaration still enforces at commit.
    fbox = make_sandbox(config={
        "categories": {"money": {"paths": ["Trading/Execution/"], "adjudicate": True}}
    })
    sandboxes.append(fbox)
    git(fbox, "init", "-q")
    f_risky = os.path.join(fbox, "trading", "execution", "order.py")
    os.makedirs(os.path.dirname(f_risky), exist_ok=True)
    with open(f_risky, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    git(fbox, "add", "trading/execution/order.py")
    check("commit gate, case-mismatched declaration, no stamp, blocks",
          run_hook(COMMIT_GATE, payload("Bash", fbox, command="git commit -m 'test'")), 2)

    # Commit gate: schema category is adjudicate false, no stamp required.
    d = make_sandbox(config=CONFIG)
    sandboxes.append(d)
    git(d, "init", "-q")
    mig = os.path.join(d, "migrations", "0001.sql")
    os.makedirs(os.path.dirname(mig), exist_ok=True)
    with open(mig, "w", encoding="utf-8") as f:
        f.write("select 1;\n")
    git(d, "add", "migrations/0001.sql")
    check("commit staging non-adjudicated category, passes without stamp",
          run_hook(COMMIT_GATE, payload("Bash", d, command="git commit -m 'mig'")), 0)

    # Commit gate: legacy money-paths.json fallback still enforces.
    git(c, "init", "-q")
    os.makedirs(os.path.dirname(c_risky), exist_ok=True)
    with open(c_risky, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    git(c, "add", "trading/execution/order.py")
    check("commit gate legacy fallback, no stamp, blocks",
          run_hook(COMMIT_GATE, payload("Bash", c, command="git commit -m 'test'")), 2)

    for s in sandboxes:
        shutil.rmtree(s, ignore_errors=True)

    failed = [n for n, ok in RESULTS if not ok]
    print("%d/%d cases passed" % (len(RESULTS) - len(failed), len(RESULTS)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
