---
name: verify-up
description: Spawn an independent verifier at a tier at least equal to the generator to confirm or reject completed work against its pre-registered bar. Mandatory before irreversible, money-touching, or automated-execution work lands.
---

# /verify-up

The generator is structurally the wrong agent to certify its own output.  This skill runs the maker-checker split: a fresh-context verifier grades the work against the pre-registered bar, confirm or reject only.

## Step 1: decide the verifier tier

At least as strong as the generator, stronger when the cost of a wrong pass is high.  Mechanical work → verify at standard.  Standard work → verify at standard or judgment.  Judgment-tier work that is irreversible, money-touching, or feeds automated execution → verify with `adjudicator`; that pairing is mandatory, not optional.  For routine reversible inline work, skip this skill entirely; the generator's own adversarial re-read is enough.

## Step 2: spawn the verifier

Spawn `independent-verifier` (or `adjudicator` when step 1 requires it) with a model override matching the chosen tier and the tier tag in its description.  The verifier is ALWAYS one of those two verify-only agents: never verify with a producer agent type (`implementer`, `judgment-designer`), whatever model it runs on.  A producer's definition permits designing and repairing, and a verifier that can repair is a second generator, not a check (deviation observed live in the E10 eval, 2026-07-06).  The verifier prompt contains exactly: the bar text verbatim from the TODO entry, the paths or artifacts to judge, and how to run the checks.  It does not contain the generator's reasoning, narrative, or confidence; independence is the point.

## Step 3: act on the verdict

**CONFIRM**: accept, record the outcome in the TODO entry, and proceed to landing the work.  When the verifier was the adjudicator (money-touching or irreversible work), also stamp `.adjudication-pass` at the project root, first line beginning with the word CONFIRM followed by the unit and date (the commit gate reads only a first line starting with CONFIRM as a pass); the commit gate requires this fresh stamp for any commit staging files under the project's adjudicated paths (`.claude/risk-paths.json` categories with adjudicate true; legacy `.claude/money-paths.json` honored), so an unadjudicated risk commit is blocked rather than trusted.
**REJECT**: do not negotiate with the verdict and do not land partial work.  Route the named failures back through `/escalate`.  The verifier never repairs; regeneration happens at the generator tier or one above, and the verifier runs again on the new output.

In both cases the verdict block reaches the human verbatim: quote it in full, never paraphrase, summarize, or soften it.  The orchestrator may add context around the quoted block but never restates it, because a rewritten rejection or a dropped caveat is the highest-stakes synthesis failure the orchestrator seat can commit, and it is invisible to the human by construction.

If the verifier reports "bar is not checkable as written", fix the bar via `/bar` step 3 (recorded revision), then re-verify.  That is a process failure worth a line in the smells checklist if it recurs.
