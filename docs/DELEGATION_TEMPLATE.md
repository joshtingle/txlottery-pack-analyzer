# Delegation Prompt Template

Every delegated prompt fills every slot below.  A slot you cannot fill is a signal: either the task is not ready to delegate, or it is small enough to do inline.  If filling the template takes longer than doing the task, do the task.

The agent description shown in the harness list must carry the model tier in brackets, for example `Sweep log dir for OOM lines [haiku]`, so the running-agents view always shows which model is doing what.

## The slots

```
TASK: <one sentence, exact and judgment-free>

CONTEXT: <exact paths to read first; nothing vague like "the config">

STEPS: <numbered, with exact commands or edit specs; the agent may not reorder>

EXPECTED OUTPUT: <what done looks like, concretely: file states, counts, output shapes>

BAR: <the pre-registered check that decides pass or fail, as a runnable command
     or recomputable value; "looks fine" is not a bar>

FAILURE AND STOP CONDITIONS: <what counts as failure; when to stop mid-task and
     report instead of continuing; never loop on a repeating error>

RETRY RULE: <"retry once, idempotent" or "no retry"; nothing open-ended>

GUARDRAILS: <explicit list of paths, tables, branches, and systems that must not
     be touched, including the tempting adjacent ones>

REPORT: <what the final message must contain; for mechanical work, data not prose>
```

## Slot notes

**TASK** states the work, not the goal behind it.  A mechanical agent given a goal will improvise; given a task, it executes.  If the goal matters, the orchestrator holds it.

**BAR** is written before the work starts and travels with the prompt.  The verifier (see `.claude/agents/independent-verifier.md`) checks against this exact text, so write it checkable: a command with an expected exit code, a number with a tolerance, a diff that must be empty.

**GUARDRAILS** name the near-misses.  "Do not touch the database" is weaker than "read from `staging.events` only; never write to any table; never touch `prod.*`".  Negative scope prevents the most expensive class of delegation failure.

**REPORT** for run-and-report supervision must demand verbatim error text on failure.  Summaries of errors lose the one line that mattered.

## What to delegate, what never to delegate

Spend the expensive model on judgment and the cheap models on mechanics.  Before starting any task, ask: does this need design sense, interpretation, or a decision?  If not, delegate it to a background agent on a cheaper model and keep the main session free.

Delegate (sonnet, or haiku when it is pure run-and-report): long-running supervision (backfills, batch jobs, migrations, watching a build to completion with idempotent reruns); noisy-output work where the agent absorbs hundreds of progress lines and reports a summary; bulk mechanical execution against an exact spec (scripted sweeps, log triage, repetitive lookups, broad searches via the Explore agent type).

Never delegate: design, result interpretation, or anything that ends in a decision (cheap models execute, they do not decide what results mean); safety-critical or money-touching code; writing `CHANGES.md` entries or any doc content that records a decision or rationale; git commits and pushes (the main session reviews delegated output before anything lands).

## Graph shape rules

The delegation graph stays one level deep: delegated agents are leaves and never spawn subagents.  A leaf that finds out-of-scope work reports it upward, never chases it sideways.  Cap parallel fan-out at about four agents and run the rest as a second wave.  When several concurrent agents each write files, give each its own git worktree and remove it when the task completes; sequential delegation needs no isolation.

## Tier reminder

Route by the signals in `docs/MODEL_ROUTING.md`, not by gut feel: reversible and fully specified goes to mechanical [haiku]; a clear-target change with tests goes to standard [sonnet]; design, interpretation, money, safety, schema, or a recorded definition goes to judgment [opus]; irreversible work is verified by the adjudicator before it lands.  The delegation graph stays one level deep and fan-out caps at about four concurrent agents.
