---
name: escalate
description: Handle a failed bar or rejected verification by diagnosing, climbing one tier, and retrying, capped at two climbs, then surfacing to the human with a structured escalation report. The only sanctioned path from failure to human.
---

# /escalate

Failure inside the loop is normal and resolves inside the loop.  The human is the escalation target of last resort, interrupted only for the three reasons at the bottom.

## Step 1: diagnose before climbing

Read the actual failure: the verifier's named failures or the bar's verbatim red output.  Classify it:

- **Spec defect**: the delegation prompt was missing or wrong in a slot (vague step, absent stop condition, wrong path).  Fix the prompt and retry at the SAME tier.  A spec defect is the orchestrator's failure; climbing tiers to compensate for a bad spec wastes the premium model.
- **Bar defect**: the bar was not checkable or tested the wrong thing.  Revise via `/bar` step 3 and re-verify without regenerating.
- **Capability failure**: the spec and bar were sound and the work is still wrong.  Climb one tier and regenerate with the failure evidence included in the new prompt.

## Step 2: climb, capped

One tier per climb (mechanical → standard → judgment → adjudicator-verified judgment), maximum two climbs per unit of work.  Each retry prompt includes: the original spec, the bar, and the verbatim failure from the previous attempt.  Never resend the failed prompt unchanged, and never retry more than once at the same tier on the same evidence.

## Step 3: surface to the human, exactly three triggers

1. **Blocking ambiguity**: intent itself is unclear and a wrong guess wastes real work or changes a recorded agreement.
2. **Irreversible or out-of-scope action**: destructive operation, money or safety action, schema change with no migration planned, change to a Core definition or headline number.
3. **Exhausted ladder**: two climbs spent and the bar is still red.

## The escalation report format

When surfacing, present exactly this, briefly: the task and its bar; each attempt as tier, what changed in the prompt, and the failure evidence verbatim; your diagnosis of why the ladder failed; and one recommended next action with its cost.  A raw "it did not work" is not an escalation.  After resolution, record the outcome in `TODO.md`, and if a failure slipped past the bar, add the regression test and the smells-checklist line in the same commit.
