# Model Routing

How a session decides which model does which piece of work, so the cheapest capable model sits in the heaviest seat and the expensive models run only where they earn their cost.  This is the deep version of the "Model routing" section in `CLAUDE.md`.  It is written to be model-agnostic: when a new model ships, you edit one table, not the policy.

## The core principle

The main context agent is the most expensive seat in the system regardless of which model fills it, because it carries the whole accumulating conversation, re-reads context every turn, and churns the prompt cache.  Whatever model runs there is multiplied by the largest token volume in the setup.  So the orchestrator should be the cheapest model that can still route reliably, and the premium models should run only as short, fresh-context bursts inside subagents, where there is no accumulated history to pay for.

The orchestrator's primary function is dispatch: classify the work, send it to the right tier, run the verification loop, and surface to the human only when the loop cannot resolve itself.  It does not need to be smart enough to recognize when a task is subtly beyond it, because routing does not rely on the orchestrator judging its own competence.  It relies on two things the orchestrator can do reliably: apply a lookup table of observable signals, and react to checkable evidence of failure.

## The role tiers (model-agnostic)

Work is routed to a role, never to a model name directly.  The roles are stable; the model behind each role changes as the frontier moves.

- **inline** -- trivial work the orchestrator does itself, no subagent.  The floor that stops over-orchestration.
- **mechanical** -- well-specified, judgment-free execution: scripted file sweeps, bulk edits to an exact spec, log triage, broad searches, run-and-report supervision.
- **standard** -- normal implementation: most coding, most tests, most refactors that have a clear target.
- **judgment** -- design, architecture, interpretation, subtle-bug hunting, and anything money-touching or irreversible.  The tier that decides what results mean.
- **adjudicator** -- the top reasoning tier, used mainly to verify the judgment tier's high-stakes output and as the escalation target when the judgment tier is uncertain.  Reserved for the few decisions you cannot take back.

## The model map (the only thing you edit when models change)

This single table binds roles to models.  Onboarding a new model is a one-line edit here plus a benchmark to place it on the price/capability frontier.  Nothing else in this doc changes.

| Role | Model (current) |
|---|---|
| inline | (the session's orchestrator model) |
| mechanical | haiku |
| standard | sonnet |
| judgment | opus |
| adjudicator | fable (personal calibration; the shipped template default is opus) |

When the map changes in either direction (a stronger model arrives, or the top tier becomes unavailable), adjudicator always points at the strongest available tier.  A SessionStart hook (`adjudicator_check.py`) injects this check into every session: it reads the pinned model from `.claude/agents/adjudicator.md`, and when a stronger tier is available the session asks the owner before anything repoints.  The model never repoints on its own.

The repoint procedure, on an owner yes, one commit: (1) `.claude/agents/adjudicator.md` frontmatter `model:` line plus the tier tag in its description (the spawn tier gate blocks tag/model mismatches); (2) the map table above, plus any personal-calibration copy of this doc; (3) the `AGENT_TIERS` fallback in `.claude/hooks/routing_ledger.py` (ledger attribution only).  Then sync the changed files to the machinery-carrying projects and run the eval set in `docs/PROCESS_EVALS.md`; it is the regression suite that says exactly which behaviors degrade on the new tier.

## Routing signals to starting tier

The orchestrator picks a STARTING tier from observable signals, not from a guess about difficulty.  Start low; the loop climbs on evidence.

- Reversible, well-specified, single-file, no interpretation -> **mechanical**.
- Normal feature or fix with a clear target, a few files, tests exist -> **standard**.
- Touches money, safety, security, schema migrations, auth, or a recorded "Core definition" / "Current headline number"; or the request is ambiguous about intent; or it spans many subsystems; or it is a design or architecture choice -> **judgment**.
- Irreversible and high-stakes (a destructive migration, a trade or payment, a prod-affecting deploy, a number about to be shown to leadership) -> **judgment** to produce, **adjudicator** to verify before it lands.

The "judgment" and "adjudicator" triggers are deliberately the same categories as the "never delegate" list in `CLAUDE.md`.  The orchestrator does not judge whether those are hard; it only detects that the task is in the category, which it can do reliably.

## The unit-of-work loop

Every delegated unit of work runs as a loop, not a single shot.  This is what lets the system minimize human interaction: the human is an escalation target of last resort, not a step in the normal path.

1. **Classify** -- pick the starting tier from the routing signals.
2. **Generate** -- the worker at that tier produces the candidate output.
3. **Verify** -- check it against a pre-registered, checkable bar: a test suite, a query result, a recomputed number, a schema diff, a lint pass.  The bar is written down before the work starts, in the form of a pre-registered decision bar (operating-discipline rule 3).  "Looks fine" is not a bar.
4. **Decide** -- if it passes, accept and record.  If it fails, diagnose, escalate one tier, and retry, up to a fixed cap (default 2 climbs).
5. **Escalate to human** -- only for the three reasons below.
6. **Record** -- write the outcome to state, and if a failure slipped past the bar, add a regression test and a smells-checklist line in the same step (incidents become procedure, rule 6).

For trivial work the loop collapses to inline-do-it-and-move-on.  Do not wrap a one-line edit in a verification ceremony; the floor matters as much as the ladder.

## Verify up, never down

The verifier should be at least as strong as the generator, and stronger for high-stakes work.  Verification is cheaper than generation and catches the errors the generator is structurally blind to, so the highest-return use of the adjudicator tier is checking someone else's output, not producing it.  The pattern is: generate on the cheaper tier, verify on the stronger one.  Keep the verifier independent per the "Independent verification" section in `CLAUDE.md`: different instructions, fresh context, ideally a different model, confirm-or-reject only, never repair.

## When the loop is allowed to interrupt you

The whole point is that work runs as a self-validating loop you do not have to babysit.  The loop surfaces to the human in exactly three cases, and otherwise keeps going:

1. **Blocking ambiguity** -- the intent itself is unclear and a wrong guess would waste real work or change a recorded agreement.  One sharp question beats 200 lines in the wrong direction.
2. **Irreversible or out-of-scope action** -- a destructive operation, a money or safety action, a schema change with no migration on the plan, a change to a Core definition or headline number, or anything outside the authorized data scope.  These are confirmed, never assumed.
3. **Exhausted ladder** -- the work climbed to the top tier and still could not pass the pre-registered bar.  Report what was tried, the failing evidence, and the smallest decision that would unblock it.

Everything else (a failing test the next tier fixes, a refactor that needs a second pass, a verifier rejection that the generator can address) is handled inside the loop without a human turn.

## The improvement loop

The routing policy is not static.  Two feedback paths keep it honest.  First, every failure that the bar missed but reasoning caught becomes a rule, logged with its date, cause, and the rule it produced, exactly as `CLAUDE.md` rule 6 requires.  Second, when a tier systematically over- or under-performs its assignment (the standard tier keeps failing a class of task, or the judgment tier is never needed for some category), that is a signal to move the routing line, recorded here and, if generic, promoted upstream via `TEMPLATE_NOTES.md`.  Over time the routing table and the smells checklist accumulate the calibration that no single session would hold in its head.

## Cost guardrails

- **Over-orchestration floor.**  A pure-dispatch orchestrator that fans out trivial work pays handoff tokens (spawn, context pass, result read) that dwarf the task.  Solve small things inline; delegate only when the task is big or risky enough to amortize the handoff.
- **Batch the expensive tier.**  Subagents start with a cold cache.  Do not spawn an adjudicator call per tiny item; gather high-stakes checks into one call.
- **Cap the climb.**  Two escalations is the default ceiling before the loop surfaces to the human.  An unbounded climb just spends the most expensive tokens on a task that may be mis-framed rather than hard (rule 8, three surprises).

## Local calibration

Each identity and each project can override the defaults in its own copy of this section, under a "Local calibration" heading.  Record only the deltas from this policy:

- Which categories are forced to `judgment`/`adjudicator` for this project's risk profile.
- The pre-registered bars for this project's recurring units of work.
- Any tier remap (for example, a project where the standard tier is too weak for the domain and should start at `judgment`).

Keep the canonical roles and loop intact; calibrate only the thresholds and the bars.
