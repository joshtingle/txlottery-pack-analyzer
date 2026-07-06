---
name: bar
description: Pre-register the checkable acceptance bar for a unit of work before generation starts. Refuses vague bars. Invoke before implementing any feature, fix, or script, whenever the request's acceptance criterion is subjective ("make sure it looks right", "should look correct"), and before any experiment, benchmark, or comparison. Invoke even when the request already states the bar; recording it in TODO.md is what binds the verifier and the audit trail to it.
---

# /bar

A bar is the pass/fail criterion written down before the work begins, so the decision cites the bar and never post-hoc persuasion.  The verifier will check against the bar's exact text, so it must be checkable by something other than any agent's claim.

## Step 1: write the bar

Append to the task's entry in `TODO.md` a line of the form:

```
BAR: <check> | <threshold> | <stability>
```

Where **check** is a runnable command or recomputable value (a test command, a query, a diff target, a metric), **threshold** is the exact pass condition (exit code 0, value within tolerance X of reference Y, diff empty, count equals N), and **stability** is how repeatable it must be (one clean run, or N runs, or matches the reference as of a date).  Default for code work: `BAR: <project test command> and <project lint command> | both exit 0 | one clean run`.

## Step 2: the vagueness gate

Reject your own bar and rewrite it if it contains any of: "looks", "reasonable", "sensible", "works", "correct", "good", "clean" (as a judgment), or any criterion a model would have to opine on rather than execute.  The test: could `independent-verifier` decide this bar using only commands and comparisons, with zero taste?  If no, it is not a bar yet.

Weak: `BAR: dashboard numbers look right`.
Strong: `BAR: SELECT count(*) FROM marts.active_customers | equals 2847 +/- 0 vs CLAUDE.md headline | single run as of 2026-07-05`.

## Step 3: stamp the gate marker

Write the same bar text to `.current-bar` at the project root (overwrite; the file is gitignored and holds the active bar).  The bar gate hook blocks creation of new code files while no fresh marker exists, so this stamp is what unlocks implementation.  The marker expires after four hours; re-stamp when registering the next bar.

## Step 4: bind it

The bar text travels verbatim in the delegation prompt's BAR slot and is what `/verify-up` hands the verifier.  If mid-task you discover the bar was wrong, you may revise it, but the revision is recorded in the TODO entry with a one-line reason before any result is judged against it.  Silently moving the bar after seeing results is the exact failure this skill exists to prevent.
