---
name: routing-review
description: Summarize the routing ledger to find tier misallocation, climb clusters, and delegation waste. Run on demand or as part of a maintenance pass; reads .claude/routing-ledger.jsonl and recent TODO.md outcomes.
---

# /routing-review

The ledger exists so tier allocation is judged on evidence, not impressions.  This review answers one question: is work running at the cheapest tier that passes its bars?

## Step 1: aggregate the ledger

Read `.claude/routing-ledger.jsonl`.  Pair SubagentStart and SubagentStop events by `agent_id`.  Produce per tier: spawn count, total and median duration, and the share of spawns with no tier tag (should be zero; the tier gate blocks untagged spawns, so untagged lines mean the gate is not wired in some session).

## Step 2: cross-reference outcomes

The ledger records spawns, not verdicts; outcomes live in `TODO.md` entries (bar results, escalations recorded by `/escalate`).  For the review window, list each unit of work with its starting tier, climbs if any, and final verdict.

## Step 3: read the patterns

- **Haiku failing mechanical work** usually means specs are under-written, not that haiku is too weak: check the failed prompts against `docs/DELEGATION_TEMPLATE.md` slot by slot before concluding capability.
- **Opus or above confirming trivially** (short duration, first-pass confirm, no findings) means work is over-routed; the signal table in `/route` needs a calibration line, or the orchestrator is routing by anxiety rather than signals.
- **Repeated same-tier retries on one task shape** means a missing playbook: the knowledge to spec that shape correctly does not exist yet in `docs/playbooks/`.
- **Verifier rejections clustering on one bar pattern** means the bar template for that work type is weak; fix it once in the relevant skill or playbook, not per task.

## Step 4: report and act

Output a short table (tier, spawns, median duration, climbs, rejects) and at most three recommended changes, each naming the exact file to edit (signal table line, template slot, playbook gap).  A recommendation without a target file is an observation, not a recommendation.  Record adopted changes in `TEMPLATE_NOTES.md` as candidate upstream improvements per `docs/UPSTREAMING.md`.
