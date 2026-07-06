# Playbook: Incidents Become Procedure

**Trigger**: any failure that slipped past the bar, the tests, or a hook and was caught by anything else (reasoning, a human, a downstream effect, an alarmed number).  Also every failure an unattended loop hits, without exception.  A bug the tests caught is not an incident; the system worked.

The point: a slipped failure proves a hole in the machinery, and the machinery is what must change.  Fixing only the bug spends the incident and keeps the hole.

## Steps

1. **Fix the bug and the hole in the same commit.**  The commit carries three things: the fix, a regression test that reproduces the slip and fails on the pre-fix code, and one line added to the project's smells checklist in `CLAUDE.md`, phrased as a check the next agent can actually run or ask ("when X, verify Y before trusting Z").  Same commit, not a follow-up; follow-ups do not happen.

2. **Log it.**  One `CHANGES.md` entry: date, symptom, root cause, and the rule it produced.

3. **Classify which layer of machinery failed**, because that names the file to edit:
   - **Bar too weak**: the pre-registered bar passed broken work.  Strengthen the bar pattern where it is written (`/bar` examples, the playbook for that work type), not just this task's bar.
   - **Spec hole**: the delegation prompt omitted the requirement.  The fix is a slot note in `docs/DELEGATION_TEMPLATE.md` usage, and `/escalate` should have caught it as a spec defect.
   - **Knowledge gap**: no playbook covered the shape.  Add the line, or the playbook.
   - **Enforcement gap**: a rule existed and was skipped.  Rules that get skipped stop being prose and become hooks.
4. **Promote on the second firing.**  The first occurrence earns a smells line.  The same smell firing twice earns promotion up the enforcement ladder: checklist line to hook, or to a process eval in `docs/PROCESS_EVALS.md`.  Enforce over trigger over remind; a checklist line that keeps firing is a reminder that has proven insufficient.

**Exit condition**: the fix commit contains test plus smells line, the `CHANGES.md` entry exists, and the classification named a machinery file that was actually edited (or a recorded reason why not).

## Worked example 1: hooks failing open on malformed payloads (this repo, 2026-07-05)

The slip: all four new enforcement hooks parsed stdin JSON and silently allowed the action on parse failure.  Red tests initially "passed" while two of them were void, because the test payloads themselves were malformed and the hooks failed open; caught by reasoning about why a third, unrelated error appeared, not by the tests.  For the commit gate this class of slip is a real hole: a malformed real-world payload (Windows backslash paths, which the pre-existing `track_agents.py` repairs for exactly this reason) would wave a red-bar commit through.

Step 1 in the fix commit: the tolerant-parse repair ported into all four hooks, plus a regression test feeding raw-backslash payloads that must still block.  Step 3 classification: enforcement gap inside the enforcement itself, and a bar weakness (the red-test bar did not require proving the test payloads were valid).  Step 4 promotion happened immediately: eval E12 in `docs/PROCESS_EVALS.md` now covers the gate, so the check outlives this session's noticing.  The smells line this produced: when a fail-open parser guards anything, test it with malformed input before trusting any of its green results.

## Worked example 2: the research-population mismatch (auto-trader, 2026-07-01, commit b11727e)

The slip: for weeks, every backtest yardstick (the burn-in expectation band, two recorded adoption bases) was computed on a population nearly disjoint from what the system actually traded.  The research harness prefiltered each day to the top 25 symbols by raw RVOL descending; the live scanner had been switched to a band-aware fitness ranking on 2026-06-11 precisely because raw-RVOL ranking measured adverse, and the fix never reached the harness.  Caught not by any test but by a deliberate sim-versus-live replay that found 1 of 49 live symbol-days present in the harness's candidate pool.

Step 1 and 2: the fix commit added an additive `ranking="fitness"` parity mode to the harness (byte-identical default preserved), and the `CHANGES.md` entry names the incident and the rule it produced.  The re-baseline rule was applied without flinching: every absolute yardstick was marked stale where recorded, and an eleven-study wave rebuilt the session library under parity, because comparisons against a moved population are not conservative, they are wrong.

Step 3 classification, and why it is the interesting part: this was a knowledge gap wearing a bar weakness.  No procedure said "a live-side change to selection logic invalidates the research harness until parity is re-verified."  Now one does: the standing parity requirement (backtests must reconstruct live's exact selection path or they are not valid yardsticks) plus a smells line about harness divergence.  Step 4's promotion target is pre-registered: if harness divergence fires again, parity verification becomes a scheduled check, not a rule someone remembers.

A coda on why smells lines are claims, not folklore: a fresh-context re-derivation drill on this incident (2026-07-05) verified from the code's own overlap constants that the recorded one-line cause understated the miss.  Raw-RVOL ranking versus fitness ranking was one of three compounding axes, alongside the RVOL frame mismatch (full-session versus causal elapsed-normalized) and retroactive universe drift, and fixing ranking alone recovered only 11 of 49 symbol-days.  The checklist line was corrected the same day.  When a drill or a verifier contradicts a recorded incident line, the line gets fixed; a smells checklist that cannot be wrong is a smells checklist nobody checked.
