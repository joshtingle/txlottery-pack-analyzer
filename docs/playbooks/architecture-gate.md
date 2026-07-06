# Playbook: The Architecture-First Gate

**Trigger**: before implementing any non-trivial change.  Non-trivial means any of: a new module or dependency, a new layer, flag, or special case in existing code, the second workaround in the same area, or anything a future reader would ask "why is it shaped like this?" about.  One-line fixes and spec-following edits pass the gate silently.

## Steps

1. **State the shape question in one sentence.**  If this codebase had been designed with this requirement from day one, where would the change live and what would it look like?  The distance between that answer and the change you were about to make is the debt being priced.

2. **List the forces, briefly.**  What varies versus what is stable, who calls this, and what breaks if the requirement shifts again in the same direction.  Three or four lines; this is aiming, not a design doc.

3. **Record one of three verdicts** in the task's TODO entry before writing code:
   - **sound**: the change lives where the day-one design would put it.
   - **acceptable-with-debt**: wrong shape, right now.  Name the debt in one line AND the trigger that forces repayment ("third consumer of this data", "when the second exchange is added").  Debt without a repayment trigger is just decay with a receipt.
   - **wrong-approach**: stop.  Surface it with the shape question and your one-sentence answer.  No code; bad designs do not get fixed by more code layered on top.

4. **The backstop.**  Refactoring the same area for the third time, or adding a workaround to dodge a layering issue, is an automatic wrong-approach review regardless of how the change feels.  The gate at step 3 is the primary detector; this is the tripwire for what it missed.

**Exit condition**: a verdict line exists in the TODO entry dated before the implementation commit, and every wrong-approach verdict produced an escalation instead of a diff.

## Worked example 1: the commit gate's marker protocol (this repo, 2026-07-05)

Requirement: make a red-bar commit impossible rather than prohibited.  The obvious shape, a PreToolUse hook that runs the full test suite on every `git commit`, failed the gate at step 2: hooks run synchronously with a timeout of seconds, test suites take minutes, and the hook fires on every Bash call that mentions commit.  The forces (slow suite, fast hook, frequent trigger) made it wrong-approach; coding it anyway would have meant either a useless timeout or disabling the hook within a week.

The recorded alternative: a marker protocol.  `run_bar.py` runs the suite on its own time and stamps `.claude/last-bar-pass` only on green; the hook's job shrinks to a millisecond freshness-and-content check of the marker.  Verdict on the marker protocol itself: acceptable-with-debt.  The debt: a thirty-minute freshness window is a heuristic, and a commit of files changed after the stamp can slip through inside it.  The repayment trigger, recorded with the verdict: if `/routing-review` or an incident ever shows a stale-marker commit, the marker gains a working-tree hash and the window goes.

## Worked example 2: the stream-engine consolidation (steward, 2026-06-11 proposal, shipped through 2026-07-05)

The backstop, not the gate, caught this one, which is why both exist.  Recurring-bill detection had grown into seven endpoint pipelines (`/upcoming`, `/coaching`, `/overview`, and four others) each computing streams with slightly divergent logic, and fixes kept landing per-pipeline: the FW Water fragmentation fix, the Walmart dedup fix, each patched where its symptom surfaced.  By the third fix to the same conceptual area, the automatic wrong-approach review fired.

The step 1 shape question: if the system had been designed knowing bills recur, detection would run once, in one place, and everything would read its output.  The forces (step 2): detection logic varies rapidly (every incident tuned it), endpoints multiply, and any divergence between two pipelines is a silent wrong answer on a financial screen.  Verdict: wrong-approach for the per-endpoint patching, recorded in `docs/CLASSIFICATION_REDESIGN.md` as a design before any code.

The redesign: `computeStreamEngine` runs only on the write path after sync, persists to `recurring_streams`, and every endpoint reads through `loadStreamState`, one source of truth replacing seven.  The consolidation is also what made later incidents cheap: the zombie-row guard and the staleness rule were each one fix in one place, where the pre-consolidation shape would have needed seven.  That is the gate's payoff in its purest form: the cost of wrong shape compounds, and so does the return on fixing it.
