---
name: route
description: Classify a task to its starting tier (inline, mechanical, standard, judgment) from observable signals. Invoke before starting ANY non-trivial unit of work, inline or delegated, including features, fixes, scripts, and refactors; it pre-registers the bar via /bar before generation begins and emits a filled delegation prompt when the work leaves the main session.
---

# /route

Input: a task description, from the user or from your own decomposition.  Output: a starting tier and, if the tier is not inline, a delegation prompt filled from `docs/DELEGATION_TEMPLATE.md`.  Never route by judging your own competence; apply the signal table and let the loop climb on evidence.

## Step 1: the inline floor

If the task is a one-file, few-line, reversible edit you can complete faster than writing a delegation prompt, do it inline now and stop.  Do not wrap trivial work in ceremony.

## Step 2: classify from observable signals, first match wins

1. Touches money movement, live orders, safety, security, auth, schema migration, or a recorded Core definition or Current headline number; or the request is ambiguous about intent; or it spans many subsystems; or it is a design or architecture choice → **judgment**.  Also check the project's Local calibration section in `MODEL_ROUTING.md`; calibration overrides this table.
2. Irreversible and high-stakes → **judgment** to produce, and note now that `/verify-up` must use the adjudicator before it lands.
3. Normal feature, fix, or refactor with a clear target and existing tests → **standard**.
4. Reversible, fully specified, no interpretation required (sweeps, bulk edits to spec, log triage, broad searches, run-and-report supervision) → **mechanical**.
5. No rule matched cleanly → **standard**, and record in the TODO entry which signal was ambiguous.

## Step 3: pre-register the bar

Run `/bar` for this task before spawning anything.  Generation does not start without a written bar.

## Step 4: fill and spawn

Fill every slot of `docs/DELEGATION_TEMPLATE.md`.  A slot you cannot fill means the task is under-specified: either specify it now or drop to inline.  Spawn the matching agent (`mechanical-executor`, `implementer`, or `judgment-designer`) with the model tier tag in the agent description, for example `Backfill event table [haiku]`.  Delegated agents are leaves; they never spawn their own subagents, and concurrent fan-out caps at about four.
