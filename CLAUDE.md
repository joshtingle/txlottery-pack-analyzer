# TX Lottery Scratcher Analytics

## Project Overview

A daily data pipeline and mobile-first React dashboard that identifies which
Texas Lottery scratch ticket packs offer the best risk-adjusted expected value.
The core insight is that the guarantee floor on packs transforms a pure gamble
into a bounded-loss proposition, making quantitative analysis actionable.

The project has two deliverables:
- **`tx_lottery_scraper.py`** — Python pipeline that fetches TX Lottery data and
  builds a local SQLite database of prize pool analytics
- **`tx-lottery-analyzer.jsx`** — React (single-file artifact) mobile-first
  dashboard that displays rankings and detailed analysis per game

---

## Architecture

### Data Sources

| Source | URL | Notes |
|--------|-----|-------|
| Prize CSV | `https://www.texaslottery.com/export/sites/lottery/Games/Scratch_Offs/scratchoff.csv` | Changes daily. Contains prize levels, counts claimed. |
| Game listing | `.../all.html` | CMS page listing all active games with detail page links |
| Detail pages | `.../details.html_NNNNNN.html` | Per-game page with pack size, guarantee, total tickets printed, launch odds |

**WAF constraint:** The TX Lottery site blocks all server-side fetches (Cloudflare
WAF). Data must be fetched from a local machine where the browser session passes
the WAF. Claude Code and local Python work fine. Artifact sandboxes and CI do not.

### Database Schema (SQLite — `tx_lottery.db`)

Three tables:

**`games_static`** — scraped once per game from detail pages, rarely changes
```
game_number, game_name, ticket_price, pack_size, guarantee_per_pack,
total_tickets_printed, overall_odds_launch, detail_url
```

**`prize_levels`** — one row per prize tier per snapshot date
```
game_number, snapshot_date, prize_amount, total_printed, claimed, remaining,
retention_rate
```

**`games_analysis`** — computed analytics, one row per game per snapshot
```
game_number, snapshot_date, maturity, sell_through, ev_per_pack,
roi_on_max_loss, composite_conc, win_rate_ratio, ev_given_win_ratio,
entropy_delta, adj_prof_score, verdict, ... (many computed fields)
```

### Scraper Modes

```bash
python tx_lottery_scraper.py              # full run
python tx_lottery_scraper.py --bootstrap  # re-fetch all detail pages
python tx_lottery_scraper.py --daily-only # CSV only, skip detail scrape
python tx_lottery_scraper.py --db sqlite  # force SQLite (default)
```

Runs via Windows Task Scheduler daily at 6 AM.

---

## Analytics Framework

All metrics are computed in the scraper and stored in `games_analysis`.
The dashboard reads from `tx_lottery_latest.json` (exported after each run).

### Core EV Model

**Sell-through anchor** — sell-through rate is estimated from the smallest prize
tier's claim rate (not overall maturity). This is intentional: small prizes are
cashed almost immediately, so their claim rate is the best proxy for actual tickets
sold. Using overall maturity over-estimates tickets remaining for games where
top prizes have been hit disproportionately.

```
sell_through    = smallest_prize_claimed / smallest_prize_printed
remaining_tix   = total_tickets_printed × (1 - sell_through)
ev_per_ticket   = sum(remaining_i × amount_i) / remaining_tix   [all tiers]
ev_per_pack     = ev_per_ticket × pack_size
above_guarantee = ev_per_pack - guarantee_per_pack
roi_on_max_loss = above_guarantee / max_loss_per_pack
max_loss        = pack_cost - guarantee_per_pack
```

### Pool Quality Signals

| Signal | Formula | Interpretation |
|--------|---------|----------------|
| **Win rate drift** | `current_win_rate / launch_win_rate` | >1.0× = more winners per remaining ticket than at launch |
| **EV\|win drift** | `ev_given_win_current / ev_given_win_launch` | >1.0× = average winning ticket worth more than at launch |
| **Entropy delta** | `current_entropy - launch_entropy` | Negative = prizes concentrating into fewer tiers |
| **Weighted skew** | Prize-$-weighted deviation from overall retention | Positive = big prizes retaining better than average |

### Scarcity-Tiered Concentration

Prize levels are classified by scarcity (1-in-X odds):

| Tier | Threshold | Signal |
|------|-----------|--------|
| 💎 ultra_rare | 1 in 500,000+ | True jackpots — hypergeometric pack probability |
| 🔴 rare | 1 in 50,000+ | Major prizes — stable concentration signal |
| 🟠 scarce | 1 in 5,000+ | Big prizes — meaningful drift signal |
| 🟡 uncommon | 1 in 500+ | Mid prizes — low signal, use for EV only |
| ⚪ common | < 1 in 500 | Base prizes — EV anchor only, concentration is noise |

**Composite concentration** weights each meaningful tier's concentration ratio by
`tier_rank² × ln(prize_amount)`. Ultra-rare prizes get ~16× the weight of scarce
prizes. Games with zero meaningful tiers (e.g. $100/$200/$500/$1,000) get a
neutral multiplier — concentration analysis is not applicable to them.

### Composite Profitability Score

```
base_score  = roi_on_max_loss × maturity_confidence × floor_protection

maturity_confidence = (m² × (1-m) × 6)  clamped 0–1, peaks at ~65% sold
floor_protection    = guarantee / pack_cost

adj_score = base_score
          × sigmoid_mult(composite_conc,  k=6,  max_boost=±0.45)
          × sigmoid_mult(jp_conc_ratio,   k=4,  max_boost=±0.25)
          × sigmoid_mult(win_rate_ratio,  k=8,  max_boost=±0.12)
          × sigmoid_mult(ev_given_win_ratio, k=10, max_boost=±0.10)
          × mom_mult                                    [Phase 1b]

sigmoid_mult(x, k, b) = 1 + tanh(k × (x - 1.0)) × b
mom_mult = 1 + tanh(115 × momentum_7d) × 0.10   [anchored at 0, not 1]
```

`momentum_7d` = (composite_conc now − composite_conc ~7 days ago) / days,
using the snapshot closest to 7 days back (5–10 day window accepted; neutral
1.0 when unavailable). Applied inside `compute_velocity_metrics()`, which
therefore MUST run before `assign_verdicts()` — verdicts are percentile cuts
on the adjusted score. k=115 calibrated 2026-07-01: p90 |momentum_7d|=0.0115
earns ~87% of the boost. Backtest justification: mean momentum predicts
next-20-day concentration change (spearman r=+0.44, p<0.001, n=62); daily
momentum is white noise (SNR 0.49) while the 7-day mean is usable (SNR 1.55).

All multipliers are anchored to 1.0 at neutral — no signal produces no
adjustment. The sigmoid curve means genuinely exceptional concentration
(1.45×) separates cleanly from merely good (1.08×) without a hard ceiling.

### Verdict Tiers (percentile-based, recalibrated each run)

| Verdict | Threshold | Current cutoff |
|---------|-----------|----------------|
| Elite | Top 5% | adj_score ≥ 0.315 |
| Strong Buy | Top 18% | adj_score ≥ 0.200 |
| Consider | Top 45% | adj_score ≥ 0.125 |
| Marginal | EV > guarantee | adj_score < 0.125 |
| Avoid | EV ≤ guarantee | — |
| Too New | maturity < 10% | — |
| Nearly Exhausted | maturity > 92% | — |

Score gauge normalizes against `DB.score_max` (actual dataset max) so #1
always reads 100 and relative positions are meaningful.

### Monte Carlo Scenarios

20,000 simulated pack draws using binomial approximation per tier:
- Returns P10, P25, P50, P75, P90 of total pack return in dollars
- **Guarantee adequacy** = guarantee / P10 — above 1.5× means the floor is
  genuinely protective
- **Variance score** = P90 / P10 — lower means more predictable outcome
- **p_pack_profit** = fraction of simulated packs whose return ≥ pack cost

### Jackpot Hunter Metrics

Computed in `compute_hunter_metrics()` for three thresholds — $1k, $10k, $100k
(column suffixes `_1k`, `_10k`, `_100k`). These answer a different question
than `adj_prof_score`: not "which pack grinds the best EV" but "which game
sells the cheapest exposure to a large prize."

```
p_hit        = 1 - (1 - qualifying_remaining / remaining_tix) ^ pack_size
burn         = pack_cost - EV(prizes below threshold)     [expected net cost]
cost_per_hit = burn / p_hit          [expected total net spend per hit]
enrich       = p_hit / p_hit_at_launch_odds
```

`p_hit = 0.0` (exactly) means no live qualifying prizes — hard-gate these out
of any hunter ranking. `cost_per_hit` is NULL in that case. The two rankings
disagree almost entirely by design: a game can be Elite for grinding while
being a terrible jackpot hunt (e.g. one jackpot left across 115k packs), and
a "marginal" game can be the cheapest big-prize exposure on the board.
Hunting is negative-EV in every game; these metrics minimize the cost of
exposure, they cannot make it profitable in expectation.

---

## Dashboard (`tx-lottery-analyzer.jsx`)

Single-file React artifact. All data is embedded as a `const DB = {...}` at
the top of the file — there is no runtime API call.

### Key Design Decisions

- Responsive: single-column on mobile, 2-col tablet, 3-col desktop. Poppins font, dark gray theme
- Detail view is a full-screen page (not a modal) to avoid mobile overflow issues
- Score ring gauge normalizes against `DB.score_max` — never hardcode a max
- The `actionable` check in `GameCard` must include `"elite"` — do not remove it
- Concentration panels use `composite_conc` if available, fallback to
  `concentration_ratio` — games with no meaningful tiers show an explanatory note
- Prize table rows sorted descending by prize amount (highest at top)
- Jackpot concentration bar uses `asOdds=true` which expresses probability as
  "1 in X" — jackpot percentages are too small to read as decimals

### Data Flow for Updates

1. Run `tx_lottery_scraper.py` — writes to SQLite + SQL Server
2. Dashboard fetches from API at `VITE_API_BASE_URL/api/latest` on load
3. Push to `main` auto-deploys via GitHub Actions (API + UI workflows)

### Hunter Mode (dashboard)

Value/Hunter toggle in the filter bar. Hunter mode adds: threshold selector
($1K+/$10K+/$100K+), gold recommendation banner (cheapest hit), Session
Planner (budget input → packs, worst case, expected net spend, P(≥1 hit) —
exact formulas only, no approximations), close-date risk tags (red, within
60 days), and hunter card tiles. Detail view adds a Trends section
(inline-SVG sparklines fed by `GET /api/history/{game_number}`) and a
per-threshold Jackpot Hunter table.

### Filters and Sort Options

The dashboard has three filter controls:
- Verdict filter: Actionable (elite+strong_buy+consider) | Elite | Strong Buy |
  Consider | Marginal | All
- Price filter: All | $1 | $2 | $3 | $5 | $10 | $20 | $30 | $50 | $100
- Sort: Composite Score | ROI | EV/Pack | Win Rate Drift | EV|Win Drift |
  Concentration | Guarantee Adequacy | Lowest Variance | Lowest Max Loss |
  Best Floor | Most Mature | Velocity Divergence | Momentum | Ticket Price

---

## File Inventory

```
tx_lottery_scraper.py       Python pipeline (fetch → compute → store)
tx-lottery-analyzer.jsx     React dashboard (single-file, data embedded)
tx_lottery.db               SQLite database (not in repo — local only)
tx_lottery_latest.json      Latest export for dashboard refresh
tx_lottery.log              Scraper run log
CLAUDE.md                   This file
```

---

## Environment & Dependencies

### Python (scraper)

```
requests
beautifulsoup4
pyodbc          # optional — only needed for SQL Server mode
```

Install: `pip install requests beautifulsoup4`

### SQL Server (optional)

RDS endpoint: `jtdc-sqlsrvr.cmhhlofylcq6.us-east-1.rds.amazonaws.com`
Database: `TxLottery`

Credentials via environment variables:
```
TXLOTTERY_SERVER
TXLOTTERY_UID
TXLOTTERY_PWD
```

SQLite is the default and is sufficient for local use. SQL Server is only
needed if you want the data accessible from other machines.

### React dashboard

No build step. Single `.jsx` file designed for claude.ai artifact renderer.
Uses only: `react`, `recharts` (not currently used but available),
`lucide-react` (not currently used). No external API calls at runtime.

---

## Roadmap (Priority Order)

### Phase 1 — Velocity & Momentum ✅ SHIPPED
- ~~**Claim velocity by tier**~~ — Δclaimed/day per tier, normalized by
  total_printed. Divergence between base-tier (fast) and top-tier (slow) is
  the leading indicator of improving concentration. Stored as
  `claim_velocity_base`, `claim_velocity_top`, `velocity_divergence` in
  `games_analysis`, plus per-tier `claim_velocity` in `prize_levels`.
- ~~**Momentum**~~ — `composite_conc_today − composite_conc_prior`. Positive
  means concentration is actively improving between snapshots.
- ~~**Win rate velocity**~~ — `Δwin_rate_ratio / days_elapsed`. Positive means
  the pool is enriching faster each day.
- All three computed in `compute_velocity_metrics()` which runs after
  `assign_verdicts()` in both `run()` and `run_recompute()`.

### Phase 1b — Momentum scoring ✅ SHIPPED (2026-07-01)
- ~~**Momentum as a score multiplier**~~ — `mom_mult = 1 + tanh(115 ×
  momentum_7d) × 0.10`, folded into `adj_prof_score` before verdict
  assignment. Calibrated and justified by a 40-snapshot backtest (see Core
  EV Model section). Uses 7-day smoothed momentum; 1-day momentum was
  measured as white noise and is stored for display only.

### Phase 2 — Needs systematic detail page scraping
- **Time-adjusted pack value** — urgency premium for games closing soon
- **Guaranteed winners efficiency** — implied winners per pack from guarantee
  structure

### Phase 3 — Needs historical data
- **Cross-price normalized ROI** — compare $1 games to $100 games fairly
- **Theoretical minimum pack return** — is the guarantee mathematically
  meaningful or just marketing?

### Phase 4 — Needs external data
- **Retailer density score** — high-volume retailers deplete packs faster.
  Groundwork shipped 2026-07-03: per-game retailer locations now accumulate
  in the `retailers` table (see Retailer Locations below).
- **Second-chance drawing value** — currently ignored, adds EV for some games

### Retailer Locations (shipped 2026-07-03)

Per-game retailer scrape from the locator JSP (POST-only:
`/opencms/Games/Scratch_Offs/Retailer_Locator.jsp`, fields submitted/city/
zip/gameNumber/smoking/selfCheck). Config: `retailer_zips` (user's area,
76008 Aledo + 5 surrounding, all within ~15 mi), `retailer_games_per_run`
(rolling cap, 12), `retailer_delay_sec` (4.0 + jitter).

**WAF constraint is severe on this endpoint**: sustained bursts get 403'd
after roughly 36 POSTs (observed 2026-07-03) — much stricter than the CSV or
detail pages, and the block persists 40+ minutes. Hence: rolling coverage
(stalest games first, capped per run) and a circuit breaker (`WafBlocked`)
that aborts the entire retailer step on the first 403. NEVER raise the cap
or lower the delay without re-testing the block threshold. CSV/detail
endpoints stay reachable during a locator block (verified).

Phone validation is two-tier: heuristic `phone_flag`
(ok/out_of_region/invalid_format/missing — the lottery DB often lists the
licensee's personal cell, e.g. out-of-state area codes on local stores) and
optional Google Places enrichment (activates when `GOOGLE_MAPS_API_KEY` env
var is set; cached in `places_cache` for 30 days). UI badges: verified /
corrected / likely owner's cell / no valid number / possibly closed.
`GET /api/retailers/{game_number}` serves the latest-scrape rows, ZIP
priority order. CLI: `--retailers`, `--skip-retailers`, `--retailers-only`.
Full runs include the step by default; `--daily-only` never does.

### Dashboard improvements (no data dependency)
- ~~JSON file drop for data refresh~~ — superseded by API-backed dashboard
- Per-game historical chart (requires multiple snapshots in DB)
- Export to CSV / share sheet

### Phase 5 — Prize distribution within packs (needs quant analysis + possibly TX Lottery pack structure data)
- **Intra-pack prize clustering** — user hypothesis: large prizes are unlikely to
  appear in closely-aligned pack numbers (i.e. prizes are not clustered but spread).
  Needs a quant deep-dive: is the TX Lottery distribution uniform-random across
  ticket positions? Are there regulatory requirements on prize spacing? Does
  pack-position data exist anywhere in the public record?
  If non-random spacing is confirmed, it changes how pack-selection advice should
  be framed — a freshly-opened pack is *not* equivalent to a pack that is 30%
  sold from the middle, even at the same sell-through rate.
  **Discuss with Claude acting as principal quantitative analyst before implementing.**

---

## Known Issues / Watch-outs

1. **WAF blocks server-side fetches** — never attempt to run the scraper from
   a cloud environment, CI pipeline, or Claude Code's own network. Must run
   locally.

2. **Verdict thresholds are percentile-based** — they recalibrate every run
   as the game universe changes. A game that was "Strong Buy" last week may
   become "Consider" this week without any change to its own metrics if the
   overall field improved. This is intentional.

3. **Four games missing pack data** — Cash On The Spot, Winning 7s,
   Easy 1-2-3, Cash Frenzy (all $1 tickets). The detail pages for very
   low-priced games may not publish guarantee data. These will never have
   ROI scores.

4. **Concentration analysis not applicable to all-common games** — games like
   $100/$200/$500/$1,000 have no scarce or rarer prize tiers. The composite
   concentration multiplier correctly returns 1.0 for these. Do not apply
   concentration logic to common-only games.

5. **`adj_prof_score` is the ranking field** — not `prof_score`. All sorts,
   filters, and the score ring use `adj_prof_score`. The `prof_score` field
   is the pre-multiplier base used for decomposition display only.

6. **Claim lag is real but uncorrected** (backtest 2026-07-01, 40 snapshots).
   Aggregate realized big-tier (scarce+) claims ran 8% above the uniform-
   claiming prediction (ratio 1.082, 95% CI 1.055–1.109), consistent with
   big prizes being claimed days-to-weeks after being hit while sales
   decline. However: (a) the lag itself was not estimable from 39 daily
   flow observations (cross-correlation curve too noisy), and (b) the
   cross-sectional artifact test came back clean — high-concentration games
   showed NO deficit in realized hits (spearman r=0.003, n=52), so
   concentration/enrichment are not obviously lag mirages. Decision: no lag
   correction until ~90 snapshots exist; treat enrichment values within a
   few percent of 1.0 as noise. Re-run the backtest
   (scratchpad backtest.py pattern) before shipping any correction.