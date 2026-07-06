# Playbook: Debugging

**Trigger**: any bug whose first hypothesis did not fix it, any unexpected behavior in something that was working, or any mismatch against a recorded headline number.  For a first-hypothesis fix that works and passes the bar, this playbook is overkill; close the loop and move on.

## Steps

1. **Reproduce before touching anything.**  Find the smallest deterministic command that shows the failure and record its verbatim output.  No fix lands before a reproduction exists; a fix without a repro is a guess wearing a diff.

2. **Name the candidate frame pairs.**  Most subtle bugs are two correct datasets in different frames, not wrong values.  Write down which pairs could disagree here: adjusted versus raw, UTC versus local, cached versus live, pre-filter versus post-filter, one encoding versus another, producer's format versus consumer's parser.  This step is cheap and it aims the investigation.

3. **Observe the boundary, do not recall it.**  Read the code at the failing path and print or log the actual value crossing the suspected frame boundary.  Metadata is not evidence: commit messages and file dates do not establish what code does; only the code and the observed value do.

4. **Fix at the layer that owns the cause.**  If the fix is adding complexity (a flag, a special case, a second code path), that is the classic sign of treating the wrong layer.  Step back one layer and look again.

5. **The three-surprises stop.**  When a third unexpected thing happens inside the same task, stop patching forward.  Re-read the relevant docs, then widen: three surprises are usually one root cause wearing three costumes.

6. **Confirm the symptom is gone, not moved.**  Re-run the step 1 reproduction verbatim.  A changed error message is not a fix.  Then run the project bar.

7. **Close per the incident playbook.**  If this bug slipped past tests, the fix commit carries a regression test and a smells line (see `incident-to-procedure.md`).

**Exit condition**: the step 1 reproduction passes verbatim, the bar is green, and (when the bug slipped past tests) the regression test fails on the pre-fix code.

## Worked example 1: the void hook tests (this repo, 2026-07-05, commit 5b3abeb)

Symptom: while red-testing enforcement hooks, three failures appeared in one run: the commit gate did not block after a red bar (exit 0 where 2 was expected), the routing ledger file was never created, and bash printed an unrelated-looking "integer expression expected" error.  Two hooks looked broken in two different ways.

Steps as they played out: three surprises in one task fired step 5 before any patching.  The frame-pair list (step 2) contained "test harness's JSON frame versus hook parser's frame".  Observing the boundary (step 3) meant piping the synthetic payload straight into `json.load`: it threw `Invalid \escape` because the test injected raw Windows backslash paths, and every hook fails open on parse failure by design.  So both "hook bugs" were void tests, one root cause in the harness, not two in the hooks.

The layer-owning fix (step 4) went further than the tests: real Windows payloads can carry the same malformed backslashes (the pre-existing `track_agents.py` carries a repair regex for exactly this), so failing open on them would let real commits through the gate.  The repair was ported into all four stdin-parsing hooks, and the regression test now feeds raw-backslash payloads and requires the gate to still block.  The wrong-layer alternative, "fixing" the ledger's path handling, would have shipped two void tests and a silent hole in the commit gate.

## Worked example 2: the adjusted-versus-raw price frame (auto-trader, 2026-06-11, commit 88c47fa)

Symptom: a three-year overnight-hold backtest reported +2.97% per trade and +18,159% total.  The numbers were internally consistent, which is exactly why step 2 matters: nothing in the run looked broken.

The too-good rule fired first (an order of magnitude beyond expectation is measurement error until proven otherwise), which turned the celebration into a frame hunt.  The frame-pair list contained the project's canonical pair: daily bars are split and dividend adjusted, intraday bars are raw.  Observing the boundary (step 3) meant comparing an intraday entry price against the forward daily bars directly: at every split inside the window the comparison manufactured a fake gap return.  The mismatch was negligible over six months, dominant over three years, which is why the same pipeline had previously looked fine.

The layer-owning fix (step 4): forward daily bars are rescaled into the entry day's raw frame at the collection layer (`rescale_forward_bars`), so no downstream consumer can re-create the mismatch.  The close (step 7): the frame pair became the first line of the project's smells checklist, and every later cross-frame comparison in that repo cites it.  The wrong-layer alternative was adjusting individual backtest results, which would have left the trap armed for the next study.
