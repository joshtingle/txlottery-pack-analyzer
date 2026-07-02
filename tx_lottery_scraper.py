"""
Texas Lottery Scratcher Analytics - Daily Console Automation
============================================================
Fetches CSV + detail pages, computes pack/EV/concentration/Monte Carlo analytics,
and stages results to SQL Server (RDS) by default, or SQLite locally.

USAGE:
  python tx_lottery_scraper.py                    # full run (bootstrap + daily) → SQL Server
  python tx_lottery_scraper.py --bootstrap         # (re)fetch all detail pages
  python tx_lottery_scraper.py --daily-only        # skip detail scrape, just refresh CSV
  python tx_lottery_scraper.py --recompute         # recompute analytics for all stored dates
  python tx_lottery_scraper.py --export-csv        # dump analysis to CSV after run
  python tx_lottery_scraper.py --db sqlite         # use local SQLite instead
  python tx_lottery_scraper.py --migrate-sqlite    # one-time copy SQLite → SQL Server

SCHEDULE:  Task Scheduler daily 6:00 AM (local machine — WAF blocks cloud runners)
"""

import argparse
import csv
import io
import json
import logging
import math
import os
import random as _rng
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# ── Configuration ─────────────────────────────────────────────────────────────

CONFIG = {
    # URLs
    "csv_url":  "https://www.texaslottery.com/export/sites/lottery/Games/Scratch_Offs/scratchoff.csv",
    "all_url":  "https://www.texaslottery.com/export/sites/lottery/Games/Scratch_Offs/all.html",
    "base_url": "https://www.texaslottery.com",

    # HTTP
    "headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.texaslottery.com/",
    },
    "request_delay_sec": 1.5,
    "timeout_sec": 20,

    # SQL Server (primary — RDS)
    "sql_server": {
        "driver":   "{ODBC Driver 17 for SQL Server}",
        "server":   os.getenv("TXLOTTERY_SERVER", "jtdc-sqlsrvr.cmhhlofylcq6.us-east-1.rds.amazonaws.com"),
        "database": os.getenv("TXLOTTERY_DB",     "tx_lottery"),
        "uid":      os.getenv("TXLOTTERY_UID",     "tx_lottery_svc"),
        "pwd":      os.getenv("TXLOTTERY_PWD",     ""),
    },

    # SQLite (local fallback / --db sqlite)
    "sqlite_path": Path(__file__).parent / "tx_lottery.db",

    # Thresholds
    "maturity_min": 0.10,
}

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "tx_lottery.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("txlottery")


# ══════════════════════════════════════════════════════════════════════════════
# FETCH LAYER
# ══════════════════════════════════════════════════════════════════════════════

def fetch(url: str, session: requests.Session) -> str:
    resp = session.get(url, headers=CONFIG["headers"], timeout=CONFIG["timeout_sec"])
    resp.raise_for_status()
    return resp.text


def fetch_csv(session: requests.Session) -> tuple[list[dict], str]:
    log.info("Fetching prize CSV...")
    text  = fetch(CONFIG["csv_url"], session)
    lines = text.splitlines()

    snapshot_date = ""
    m = re.search(r"as of (\d{2}/\d{2}/\d{4})", lines[0])
    if m:
        snapshot_date = datetime.strptime(m.group(1), "%m/%d/%Y").date().isoformat()

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[1:])),
        fieldnames=["game_number","game_name","close_date","ticket_price",
                    "prize_level","total_prizes","prizes_claimed"],
    )
    next(reader)

    rows = []
    for r in reader:
        try:
            rows.append({
                "game_number":   int(r["game_number"].strip().strip('"')),
                "game_name":     r["game_name"].strip().strip('"'),
                "close_date":    r["close_date"].strip().strip('"') or None,
                "ticket_price":  float(r["ticket_price"].strip()),
                "prize_level":   r["prize_level"].strip().strip('"'),
                "total_prizes":  int(r["total_prizes"].replace(",","").strip() or 0),
                "prizes_claimed":int(r["prizes_claimed"].replace(",","").strip() or 0),
            })
        except (ValueError, KeyError):
            continue

    log.info(f"  CSV rows parsed: {len(rows)}  |  snapshot: {snapshot_date}")
    return rows, snapshot_date


def fetch_detail_urls(session: requests.Session) -> dict[int, str]:
    log.info("Fetching game listing page for detail URLs...")
    html  = fetch(CONFIG["all_url"], session)
    soup  = BeautifulSoup(html, "html.parser")
    links = {}

    for a in soup.find_all("a", href=re.compile(r"details\.html")):
        href = a["href"]
        text = a.get_text(strip=True)
        try:
            game_num = int(text)
        except ValueError:
            continue
        full_url = href if href.startswith("http") else CONFIG["base_url"] + href
        links[game_num] = full_url

    log.info(f"  Detail URLs found: {len(links)}")
    return links


def parse_detail_page(html: str, game_number: int) -> dict:
    result = {
        "game_number":          game_number,
        "pack_size":            None,
        "guarantee_per_pack":   None,
        "total_tickets_printed":None,
        "overall_odds_launch":  None,
        "detail_scraped_at":    datetime.now(timezone.utc).isoformat(),
    }

    m = re.search(r"Pack Size[:\s]+(\d+)\s*tickets", html, re.IGNORECASE)
    if m: result["pack_size"] = int(m.group(1))

    m = re.search(r"Guaranteed Total Prize Amount\s*=\s*\$([0-9,]+)", html, re.IGNORECASE)
    if m: result["guarantee_per_pack"] = int(m.group(1).replace(",", ""))

    m = re.search(r"approximately\s*([\d,]+)\*?\s*tickets", html, re.IGNORECASE)
    if m: result["total_tickets_printed"] = int(m.group(1).replace(",", ""))

    m = re.search(r"1 in ([\d.]+)\*{0,2}\s*[\(\.]", html, re.IGNORECASE)
    if m: result["overall_odds_launch"] = float(m.group(1))

    return result


def fetch_all_details(
    game_numbers: list[int],
    detail_urls:  dict[int, str],
    existing:     dict[int, dict],
    session:      requests.Session,
    force:        bool = False,
) -> dict[int, dict]:
    results  = dict(existing)
    to_fetch = [n for n in game_numbers if force or n not in existing]
    log.info(f"Detail pages to fetch: {len(to_fetch)} (of {len(game_numbers)} games)")

    missing_url = []
    for i, gnum in enumerate(to_fetch, 1):
        url = detail_urls.get(gnum)
        if not url:
            missing_url.append(gnum)
            results[gnum] = {"game_number": gnum}
            continue

        try:
            log.info(f"  [{i}/{len(to_fetch)}] Fetching #{gnum}...")
            html   = fetch(url, session)
            parsed = parse_detail_page(html, gnum)
            parsed["detail_url"] = url
            results[gnum] = parsed
            log.info(
                f"    pack={parsed['pack_size']}  "
                f"guarantee=${parsed['guarantee_per_pack']}  "
                f"tickets={parsed['total_tickets_printed']:,}" if parsed['total_tickets_printed'] else
                f"    pack={parsed['pack_size']}  guarantee=${parsed['guarantee_per_pack']}"
            )
        except Exception as e:
            log.error(f"  [{i}/{len(to_fetch)}] #{gnum} - error: {e}")
            results[gnum] = {"game_number": gnum, "detail_url": url}

        if i < len(to_fetch):
            time.sleep(CONFIG["request_delay_sec"])

    if missing_url:
        log.info(f"  no detail URL on listing page for {len(missing_url)} game(s): "
                 f"{missing_url} (expected for some low-price/closing games)")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS LAYER
# ══════════════════════════════════════════════════════════════════════════════

def _r(v, dp):
    return round(v, dp) if v is not None else None


def sigmoid_mult(x, k: float, b: float) -> float:
    if x is None:
        return 1.0
    return 1.0 + math.tanh(k * (x - 1.0)) * b


# Momentum multiplier (Phase 1b). Unlike the ratio multipliers (anchored at
# 1.0), momentum is a daily delta anchored at 0. k calibrated 2026-07-01 from
# 2,469 game-day observations of 7-day-smoothed momentum: p90 |m7|=0.0115
# earns ~87% of the boost. Backtest: mean momentum predicts next-20-day
# concentration change, spearman r=+0.44, p<0.001, n=62; daily momentum is
# white noise (SNR 0.49) while the 7-day mean is usable (SNR 1.55).
MOMENTUM_K     = 115
MOMENTUM_BOOST = 0.10


def classify_tiers(levels: list[dict], total_tickets: int, overall_retention: float) -> None:
    THRESHOLDS = [
        (500_000, "ultra_rare"),
        ( 50_000, "rare"),
        (  5_000, "scarce"),
        (    500, "uncommon"),
    ]
    for i, lv in enumerate(levels):
        if total_tickets and lv["total"] > 0:
            one_in = total_tickets / lv["total"]
        else:
            one_in = None
        lv["one_in"] = one_in

        if one_in is None:
            lv["tier"] = None
        else:
            lv["tier"] = "common"
            for threshold, name in THRESHOLDS:
                if one_in >= threshold:
                    lv["tier"] = name
                    break

        lv["is_meaningful"] = lv["tier"] in ("ultra_rare", "rare", "scarce")
        lv["is_jackpot"]    = (i == 0)
        lv["deviation"]     = lv["retention_rate"] - overall_retention


def shannon_entropy(counts: list) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    result = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            result -= p * math.log2(p)
    return result


def compute_composite_conc(levels: list[dict], overall_retention: float) -> tuple[float, int]:
    TIER_RANK = {"ultra_rare": 4, "rare": 3, "scarce": 2}
    meaningful = [lv for lv in levels if lv.get("is_meaningful")]
    n = len(meaningful)
    if n == 0 or overall_retention <= 0.001:
        return 1.0, 0

    w_sum = w_tot = 0.0
    for lv in meaningful:
        rank   = TIER_RANK[lv["tier"]]
        weight = (rank ** 2) * math.log(max(lv["amount"], 2.0))
        ratio  = lv["retention_rate"] / overall_retention
        w_sum += weight * ratio
        w_tot += weight

    return (w_sum / w_tot if w_tot > 0 else 1.0), n


def _poisson_sample(lam: float) -> int:
    if lam <= 0:
        return 0
    L = math.exp(-min(lam, 700))
    k, p = 0, 1.0
    while p > L:
        p *= _rng.random()
        k += 1
    return k - 1


def monte_carlo_pack(
    levels: list[dict],
    pack_size: int,
    remaining_tix: float,
    n_sims: int = None,
    pack_cost: float = None,
) -> dict | None:
    if not pack_size or not remaining_tix or remaining_tix <= 0:
        return None

    win_levels = [
        (lv["amount"], min(lv["remaining"] / remaining_tix, 1.0))
        for lv in levels if lv["remaining"] > 0
    ]
    if not win_levels:
        return None

    if _HAS_NUMPY:
        n = n_sims or 20_000
        results = _np.zeros(n)
        for amount, p in win_levels:
            results += _np.random.binomial(pack_size, p, n) * amount
        results.sort()
        pct = lambda q: float(results[min(int(q * n), n - 1)])
        p_profit = (float((results >= pack_cost).mean()) if pack_cost else None)
    else:
        n = n_sims or 5_000
        results = []
        for _ in range(n):
            v = sum(_poisson_sample(p * pack_size) * amount for amount, p in win_levels)
            results.append(v)
        results.sort()
        pct = lambda q: results[min(int(q * n), n - 1)]
        p_profit = (sum(1 for v in results if v >= pack_cost) / n if pack_cost else None)

    return {
        "p10": round(pct(0.10), 2),
        "p25": round(pct(0.25), 2),
        "p50": round(pct(0.50), 2),
        "p75": round(pct(0.75), 2),
        "p90": round(pct(0.90), 2),
        "p_profit": (round(p_profit, 4) if p_profit is not None else None),
    }


# ── Jackpot-hunter metrics ────────────────────────────────────────────────────
# For each threshold: what does a pack cost you net of sub-threshold payouts,
# and what are the odds it contains a prize at or above the threshold?

HUNTER_THRESHOLDS = [(1_000, "1k"), (10_000, "10k"), (100_000, "100k")]


def compute_hunter_metrics(
    levels: list[dict],
    pack_size: int,
    pack_cost: float,
    remaining_tix: float,
    total_tickets: int,
) -> dict:
    out = {}
    for thresh, sfx in HUNTER_THRESHOLDS:
        p_hit = burn = cost_per_hit = enrich = None

        if pack_size and pack_cost is not None and remaining_tix and remaining_tix > 0:
            qual_remaining = sum(lv["remaining"] for lv in levels if lv["amount"] >= thresh)
            p_ticket = min(qual_remaining / remaining_tix, 1.0)
            p_hit = 1.0 - (1.0 - p_ticket) ** pack_size

            ev_below = (sum(lv["remaining"] * lv["amount"]
                            for lv in levels if lv["amount"] < thresh)
                        / remaining_tix * pack_size)
            burn = pack_cost - ev_below
            if p_hit > 0:
                cost_per_hit = burn / p_hit

            if total_tickets:
                qual_printed = sum(lv["total"] for lv in levels if lv["amount"] >= thresh)
                if qual_printed > 0:
                    p_ticket_launch = min(qual_printed / total_tickets, 1.0)
                    p_hit_launch = 1.0 - (1.0 - p_ticket_launch) ** pack_size
                    if p_hit_launch > 0:
                        enrich = p_hit / p_hit_launch

        out[f"hunter_p_hit_{sfx}"]        = _r(p_hit, 8)
        out[f"hunter_burn_{sfx}"]         = _r(burn, 2)
        out[f"hunter_cost_per_hit_{sfx}"] = _r(cost_per_hit, 0)
        out[f"hunter_enrich_{sfx}"]       = _r(enrich, 4)
    return out


def build_game_records(csv_rows: list[dict], snapshot_date: str) -> dict[int, dict]:
    games: dict[int, dict] = {}

    for r in csv_rows:
        gnum = r["game_number"]
        if gnum not in games:
            games[gnum] = {
                "game_number":   gnum,
                "game_name":     r["game_name"],
                "close_date":    r["close_date"],
                "ticket_price":  r["ticket_price"],
                "snapshot_date": snapshot_date,
                "prize_levels":  [],
                "total_prizes":  0,
                "claimed_prizes":0,
            }

        if r["prize_level"] == "TOTAL":
            games[gnum]["total_prizes"]   = r["total_prizes"]
            games[gnum]["claimed_prizes"] = r["prizes_claimed"]
        else:
            try:
                amt = float(r["prize_level"].replace(",", ""))
            except ValueError:
                continue
            games[gnum]["prize_levels"].append({
                "amount":  amt,
                "total":   r["total_prizes"],
                "claimed": r["prizes_claimed"],
            })

    return games


def compute_analytics(game: dict, detail: dict) -> dict:
    ticket_price = game["ticket_price"]

    levels = sorted(
        [
            {
                "amount":         pl["amount"],
                "total":          pl["total"],
                "claimed":        pl["claimed"],
                "remaining":      max(0, pl["total"] - pl["claimed"]),
                "retention_rate": (max(0, pl["total"] - pl["claimed"]) / pl["total"]
                                   if pl["total"] > 0 else 0.0),
            }
            for pl in game["prize_levels"]
        ],
        key=lambda x: x["amount"],
        reverse=True,
    )

    pack_size           = detail.get("pack_size")
    guarantee           = detail.get("guarantee_per_pack")
    total_tickets       = detail.get("total_tickets_printed")
    overall_odds_launch = detail.get("overall_odds_launch")
    pack_cost           = pack_size * ticket_price if pack_size else None
    max_loss_per_pack   = ((pack_cost - guarantee)
                           if pack_cost is not None and guarantee is not None else None)
    downside_protection = (guarantee / pack_cost if guarantee is not None and pack_cost else None)

    if levels and levels[-1]["total"] > 0:
        sell_through = levels[-1]["claimed"] / levels[-1]["total"]
    elif game["total_prizes"] > 0:
        sell_through = game["claimed_prizes"] / game["total_prizes"]
    else:
        sell_through = 0.0

    maturity      = sell_through
    remaining_tix = (total_tickets * (1.0 - sell_through)) if total_tickets else None

    total_prizes_printed = game["total_prizes"]
    prizes_claimed       = game["claimed_prizes"]
    prizes_remaining     = total_prizes_printed - prizes_claimed
    overall_retention    = (prizes_remaining / total_prizes_printed
                            if total_prizes_printed > 0 else 1.0)
    remaining_value      = sum(lv["remaining"] * lv["amount"] for lv in levels)

    ev_per_ticket   = (remaining_value / remaining_tix
                       if remaining_tix and remaining_tix > 0 else None)
    ev_per_pack     = (ev_per_ticket * pack_size
                       if ev_per_ticket is not None and pack_size else None)
    above_guarantee = ((ev_per_pack - guarantee)
                       if ev_per_pack is not None and guarantee is not None else None)
    roi_on_max_loss = (above_guarantee / max_loss_per_pack
                       if above_guarantee is not None
                          and max_loss_per_pack is not None
                          and max_loss_per_pack > 0
                       else None)

    total_remaining_prizes = sum(lv["remaining"] for lv in levels)

    launch_win_rate  = (1.0 / overall_odds_launch) if overall_odds_launch else None
    current_win_rate = (total_remaining_prizes / remaining_tix
                        if remaining_tix and remaining_tix > 0 else None)
    win_rate_ratio   = ((current_win_rate / launch_win_rate)
                        if current_win_rate and launch_win_rate else None)

    total_launch_prizes  = sum(lv["total"] for lv in levels)
    ev_given_win_launch  = (sum(lv["amount"] * lv["total"]    for lv in levels) / total_launch_prizes
                            if total_launch_prizes > 0 else None)
    ev_given_win_current = (sum(lv["amount"] * lv["remaining"] for lv in levels) / total_remaining_prizes
                            if total_remaining_prizes > 0 else None)
    ev_given_win_ratio   = ((ev_given_win_current / ev_given_win_launch)
                            if ev_given_win_current and ev_given_win_launch else None)

    expected_winners_launch  = (pack_size / overall_odds_launch
                                if pack_size and overall_odds_launch else None)
    expected_winners_current = (current_win_rate * pack_size
                                if current_win_rate and pack_size else None)

    entropy_launch  = shannon_entropy([lv["total"]     for lv in levels])
    entropy_current = shannon_entropy([lv["remaining"] for lv in levels])
    entropy_delta   = entropy_current - entropy_launch

    classify_tiers(levels, total_tickets, overall_retention)
    composite_conc, n_meaningful_tiers = compute_composite_conc(levels, overall_retention)
    concentration_ratio = composite_conc

    jp = levels[0] if levels else None
    if jp:
        jp_amount    = jp["amount"]
        jp_printed   = jp["total"]
        jp_remaining = jp["remaining"]
        jp_conc_ratio = (jp["retention_rate"] / overall_retention
                         if overall_retention > 0.001 else 1.0)

        p_jp_launch = (jp_printed / total_tickets) if total_tickets and jp_printed else None
        p_jp_curr   = ((jp_remaining / remaining_tix)
                       if remaining_tix and remaining_tix > 0 and jp_remaining is not None
                       else None)

        p_jp_launch_pack = (1.0 - (1.0 - p_jp_launch) ** pack_size
                            if p_jp_launch is not None and pack_size else None)
        p_jp_curr_pack   = (1.0 - (1.0 - min(p_jp_curr, 1.0)) ** pack_size
                            if p_jp_curr is not None and pack_size else None)
    else:
        jp_amount = jp_printed = jp_remaining = jp_conc_ratio = None
        p_jp_launch_pack = p_jp_curr_pack = None

    top_bucket_printed   = jp_printed
    top_bucket_remaining = jp_remaining
    p_top_launch_pack    = p_jp_launch_pack
    p_top_curr_pack      = p_jp_curr_pack

    mc = monte_carlo_pack(levels, pack_size, remaining_tix, pack_cost=pack_cost)
    scenario_p10 = scenario_p25 = scenario_p50 = scenario_p75 = scenario_p90 = None
    guarantee_adequacy = variance_score = None
    p_pack_profit = None
    if mc:
        p_pack_profit = mc.get("p_profit")
        scenario_p10, scenario_p25, scenario_p50 = mc["p10"], mc["p25"], mc["p50"]
        scenario_p75, scenario_p90 = mc["p75"], mc["p90"]
        if guarantee is not None and scenario_p10 and scenario_p10 > 0:
            guarantee_adequacy = round(guarantee / scenario_p10, 4)
        if scenario_p90 and scenario_p10 and scenario_p10 > 0:
            variance_score = round(scenario_p90 / scenario_p10, 4)

    maturity_confidence = min(1.0, max(0.0, maturity ** 2 * (1.0 - maturity) * 6.0))
    floor_protection    = downside_protection

    prof_score = adj_prof_score = None
    conc_mult = jp_mult = wr_mult = evgw_mult = None

    if (roi_on_max_loss is not None
            and maturity_confidence is not None
            and floor_protection is not None):
        prof_score = roi_on_max_loss * maturity_confidence * floor_protection
        conc_mult  = sigmoid_mult(composite_conc,     k=6,  b=0.45)
        jp_mult    = sigmoid_mult(jp_conc_ratio,      k=4,  b=0.25)
        wr_mult    = sigmoid_mult(win_rate_ratio,     k=8,  b=0.12)
        evgw_mult  = sigmoid_mult(ev_given_win_ratio, k=10, b=0.10)
        adj_prof_score = prof_score * conc_mult * jp_mult * wr_mult * evgw_mult

    rec = {
        "game_number":              game["game_number"],
        "game_name":                game["game_name"],
        "snapshot_date":            game["snapshot_date"],
        "close_date":               game["close_date"],
        "ticket_price":             ticket_price,
        "pack_size":                pack_size,
        "guarantee_per_pack":       guarantee,
        "pack_cost":                pack_cost,
        "max_loss_per_pack":        max_loss_per_pack,
        "total_tickets_printed":    total_tickets,
        "overall_odds_launch":      overall_odds_launch,
        "downside_protection":      _r(downside_protection, 4),
        "sell_through":             round(sell_through, 6),
        "maturity":                 round(maturity, 6),
        "is_new_game":              int(maturity < CONFIG["maturity_min"]),
        "maturity_confidence":      _r(maturity_confidence, 6),
        "remaining_tickets_est":    _r(remaining_tix, 0),
        "total_prizes_printed":     total_prizes_printed,
        "prizes_claimed":           prizes_claimed,
        "prizes_remaining":         prizes_remaining,
        "remaining_prize_value":    round(remaining_value, 2),
        "ev_per_ticket":            _r(ev_per_ticket, 4),
        "ev_per_pack":              _r(ev_per_pack, 2),
        "expected_above_guarantee": _r(above_guarantee, 2),
        "roi_on_max_loss":          _r(roi_on_max_loss, 6),
        "launch_win_rate":          _r(launch_win_rate, 8),
        "current_win_rate":         _r(current_win_rate, 8),
        "win_rate_ratio":           _r(win_rate_ratio, 6),
        "ev_given_win_launch":      _r(ev_given_win_launch, 4),
        "ev_given_win_current":     _r(ev_given_win_current, 4),
        "ev_given_win_ratio":       _r(ev_given_win_ratio, 6),
        "expected_winners_launch":  _r(expected_winners_launch, 4),
        "expected_winners_current": _r(expected_winners_current, 4),
        "entropy_launch":           round(entropy_launch, 6),
        "entropy_current":          round(entropy_current, 6),
        "entropy_delta":            round(entropy_delta, 6),
        "n_meaningful_tiers":       n_meaningful_tiers,
        "composite_conc":           round(composite_conc, 6),
        "concentration_ratio":      round(concentration_ratio, 6),
        "top_bucket_printed":       top_bucket_printed,
        "top_bucket_remaining":     top_bucket_remaining,
        "jp_amount":                jp_amount,
        "jp_printed":               jp_printed,
        "jp_remaining":             jp_remaining,
        "jp_conc_ratio":            _r(jp_conc_ratio, 6),
        "p_jp_launch_pack":         _r(p_jp_launch_pack, 8),
        "p_jp_curr_pack":           _r(p_jp_curr_pack, 8),
        "p_top_launch_pack":        _r(p_top_launch_pack, 8),
        "p_top_curr_pack":          _r(p_top_curr_pack, 8),
        "scenario_p10":             scenario_p10,
        "scenario_p25":             scenario_p25,
        "scenario_p50":             scenario_p50,
        "scenario_p75":             scenario_p75,
        "scenario_p90":             scenario_p90,
        "guarantee_adequacy":       guarantee_adequacy,
        "variance_score":           variance_score,
        "p_pack_profit":            p_pack_profit,
        "prof_score":               _r(prof_score, 6),
        "adj_prof_score":           _r(adj_prof_score, 6),
        "conc_mult":                _r(conc_mult, 6),
        "jp_mult":                  _r(jp_mult, 6),
        "wr_mult":                  _r(wr_mult, 6),
        "evgw_mult":                _r(evgw_mult, 6),
        "verdict":                  "_pending",
        "detail_url":               detail.get("detail_url"),
        "computed_at":              datetime.now(timezone.utc).isoformat(),
    }

    rec.update(compute_hunter_metrics(levels, pack_size, pack_cost,
                                      remaining_tix, total_tickets))

    rec["_levels"] = levels
    return rec


def assign_verdicts(recs: list[dict]) -> None:
    for rec in recs:
        if not rec.get("pack_size") or rec.get("guarantee_per_pack") is None:
            rec["verdict"] = "no_data"
            continue
        if not rec.get("total_tickets_printed"):
            rec["verdict"] = "no_data"
            continue
        m = rec.get("maturity", 0.0)
        if m < CONFIG["maturity_min"]:
            rec["verdict"] = "too_new"
            continue
        ev   = rec.get("ev_per_pack")
        guar = rec.get("guarantee_per_pack")
        if ev is None or (guar is not None and ev <= guar):
            rec["verdict"] = "avoid"
            continue
        if rec.get("adj_prof_score") is None:
            rec["verdict"] = "avoid"
            continue
        rec["verdict"] = "_scoreable"

    scoreable = sorted(
        [r for r in recs if r["verdict"] == "_scoreable"],
        key=lambda r: r["adj_prof_score"],
        reverse=True,
    )
    n = len(scoreable)
    if n == 0:
        return

    elite_cut    = max(1, math.ceil(n * 0.05))
    strong_cut   = max(elite_cut,  math.ceil(n * 0.18))
    consider_cut = max(strong_cut, math.ceil(n * 0.45))

    for i, rec in enumerate(scoreable):
        if i < elite_cut:
            rec["verdict"] = "elite"
        elif i < strong_cut:
            rec["verdict"] = "strong_buy"
        elif i < consider_cut:
            rec["verdict"] = "consider"
        else:
            rec["verdict"] = "marginal"


# ── Phase 1: Velocity metrics (cross-snapshot comparison) ────────────────────

def compute_velocity_metrics(db, recs: list[dict], all_levels_map: dict,
                             snapshot_date: str) -> None:
    """Enrich analysis records with velocity metrics by comparing to the prior snapshot."""
    if db.mode == "sqlite":
        prior_row = db.conn.execute(
            "SELECT snapshot_date FROM games_analysis "
            "WHERE snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1",
            (snapshot_date,),
        ).fetchone()
    else:
        cur = db.conn.cursor()
        cur.execute(
            "SELECT TOP 1 snapshot_date FROM games_analysis "
            "WHERE snapshot_date < ? ORDER BY snapshot_date DESC",
            (snapshot_date,),
        )
        prior_row = cur.fetchone()

    if not prior_row:
        for rec in recs:
            rec.update(claim_velocity_base=None, claim_velocity_top=None,
                       velocity_divergence=None, momentum=None,
                       win_rate_velocity=None, days_since_prior=None,
                       momentum_7d=None, mom_mult=None)
        return

    prior_date = prior_row[0]
    days_elapsed = (date.fromisoformat(snapshot_date) - date.fromisoformat(prior_date)).days
    if days_elapsed <= 0:
        days_elapsed = 1

    _, prior_ga_rows = db.fetch_rows(
        "SELECT game_number, composite_conc, win_rate_ratio "
        "FROM games_analysis WHERE snapshot_date=?", (prior_date,))
    prior_ga = {r[0]: {"composite_conc": r[1], "win_rate_ratio": r[2]}
                for r in prior_ga_rows}

    # 7-day smoothed momentum: compare composite_conc to the snapshot closest
    # to 7 days back (accept 5-10 days; None outside that window).
    _, date_rows = db.fetch_rows(
        f"SELECT DISTINCT {db._top_n(12)} snapshot_date FROM games_analysis "
        f"WHERE snapshot_date < ? ORDER BY snapshot_date DESC {db._limit_n(12)}",
        (snapshot_date,))
    cur_d = date.fromisoformat(snapshot_date)
    week_date, week_gap = None, None
    for (d0,) in date_rows:
        gap = (cur_d - date.fromisoformat(d0)).days
        if 5 <= gap <= 10 and (week_gap is None or abs(gap - 7) < abs(week_gap - 7)):
            week_date, week_gap = d0, gap
    week_conc = {}
    if week_date:
        _, wk_rows = db.fetch_rows(
            "SELECT game_number, composite_conc FROM games_analysis "
            "WHERE snapshot_date=?", (week_date,))
        week_conc = {r[0]: r[1] for r in wk_rows}

    _, prior_pl_rows = db.fetch_rows(
        "SELECT game_number, prize_amount, claimed, total_printed, is_meaningful "
        "FROM prize_levels WHERE snapshot_date=?", (prior_date,))
    prior_levels = defaultdict(dict)
    for r in prior_pl_rows:
        prior_levels[r[0]][r[1]] = {"claimed": r[2], "total_printed": r[3],
                                    "is_meaningful": r[4]}

    for rec in recs:
        gnum = rec["game_number"]
        rec["days_since_prior"] = days_elapsed

        pa = prior_ga.get(gnum)
        if pa and pa["composite_conc"] is not None and rec.get("composite_conc") is not None:
            rec["momentum"] = round(rec["composite_conc"] - pa["composite_conc"], 6)
        else:
            rec["momentum"] = None

        if pa and pa["win_rate_ratio"] is not None and rec.get("win_rate_ratio") is not None:
            rec["win_rate_velocity"] = round(
                (rec["win_rate_ratio"] - pa["win_rate_ratio"]) / days_elapsed, 6)
        else:
            rec["win_rate_velocity"] = None

        prev_pl = prior_levels.get(gnum, {})
        base_vels, top_vels = [], []

        for lv in all_levels_map.get(gnum, []):
            prev = prev_pl.get(lv["amount"])
            if not prev or not lv.get("total") or lv["total"] <= 0:
                lv["claim_velocity"] = None
                continue
            delta = (lv.get("claimed") or 0) - (prev.get("claimed") or 0)
            vel = (delta / days_elapsed) / lv["total"]
            lv["claim_velocity"] = round(vel, 8)

            if lv.get("is_meaningful"):
                top_vels.append(vel)
            else:
                base_vels.append(vel)

        rec["claim_velocity_base"] = round(sum(base_vels) / len(base_vels), 8) if base_vels else None
        rec["claim_velocity_top"] = round(sum(top_vels) / len(top_vels), 8) if top_vels else None
        if rec["claim_velocity_base"] is not None and rec["claim_velocity_top"] is not None:
            rec["velocity_divergence"] = round(rec["claim_velocity_base"] - rec["claim_velocity_top"], 8)
        else:
            rec["velocity_divergence"] = None

        # Phase 1b: 7-day momentum multiplier folded into adj_prof_score.
        # Must run before assign_verdicts (percentile cuts use adjusted scores).
        wc = week_conc.get(gnum)
        if wc is not None and rec.get("composite_conc") is not None and week_gap:
            m7 = (rec["composite_conc"] - wc) / week_gap
            rec["momentum_7d"] = round(m7, 6)
            rec["mom_mult"]    = round(1.0 + math.tanh(MOMENTUM_K * m7) * MOMENTUM_BOOST, 6)
        else:
            rec["momentum_7d"] = None
            rec["mom_mult"]    = None
        if rec["mom_mult"] is not None and rec.get("adj_prof_score") is not None:
            rec["adj_prof_score"] = round(rec["adj_prof_score"] * rec["mom_mult"], 6)


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE LAYER
# ══════════════════════════════════════════════════════════════════════════════

# SQLite schema (local fallback)
_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS games_static (
    game_number             INTEGER PRIMARY KEY,
    pack_size               INTEGER,
    guarantee_per_pack      REAL,
    total_tickets_printed   INTEGER,
    overall_odds_launch     REAL,
    detail_url              TEXT,
    detail_scraped_at       TEXT
);
CREATE TABLE IF NOT EXISTS prize_levels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_number     INTEGER NOT NULL,
    snapshot_date   TEXT    NOT NULL,
    prize_amount    REAL    NOT NULL,
    total_printed   INTEGER,
    claimed         INTEGER,
    remaining       INTEGER,
    retention_rate  REAL,
    one_in          REAL,
    tier            TEXT,
    is_jackpot      INTEGER,
    is_meaningful   INTEGER,
    deviation       REAL,
    claim_velocity  REAL,
    UNIQUE(game_number, snapshot_date, prize_amount)
);
CREATE TABLE IF NOT EXISTS games_analysis (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_number                 INTEGER NOT NULL,
    game_name                   TEXT,
    snapshot_date               TEXT    NOT NULL,
    close_date                  TEXT,
    ticket_price                REAL,
    pack_size                   INTEGER,
    guarantee_per_pack          REAL,
    pack_cost                   REAL,
    max_loss_per_pack           REAL,
    total_tickets_printed       INTEGER,
    overall_odds_launch         REAL,
    downside_protection         REAL,
    sell_through                REAL,
    maturity                    REAL,
    is_new_game                 INTEGER,
    maturity_confidence         REAL,
    remaining_tickets_est       REAL,
    total_prizes_printed        INTEGER,
    prizes_claimed              INTEGER,
    prizes_remaining            INTEGER,
    remaining_prize_value       REAL,
    ev_per_ticket               REAL,
    ev_per_pack                 REAL,
    expected_above_guarantee    REAL,
    roi_on_max_loss             REAL,
    launch_win_rate             REAL,
    current_win_rate            REAL,
    win_rate_ratio              REAL,
    ev_given_win_launch         REAL,
    ev_given_win_current        REAL,
    ev_given_win_ratio          REAL,
    expected_winners_launch     REAL,
    expected_winners_current    REAL,
    entropy_launch              REAL,
    entropy_current             REAL,
    entropy_delta               REAL,
    n_meaningful_tiers          INTEGER,
    composite_conc              REAL,
    concentration_ratio         REAL,
    top_bucket_printed          INTEGER,
    top_bucket_remaining        INTEGER,
    jp_amount                   REAL,
    jp_printed                  INTEGER,
    jp_remaining                INTEGER,
    jp_conc_ratio               REAL,
    p_jp_launch_pack            REAL,
    p_jp_curr_pack              REAL,
    p_top_launch_pack           REAL,
    p_top_curr_pack             REAL,
    scenario_p10                REAL,
    scenario_p25                REAL,
    scenario_p50                REAL,
    scenario_p75                REAL,
    scenario_p90                REAL,
    guarantee_adequacy          REAL,
    variance_score              REAL,
    p_pack_profit               REAL,
    hunter_p_hit_1k             REAL,
    hunter_burn_1k              REAL,
    hunter_cost_per_hit_1k      REAL,
    hunter_enrich_1k            REAL,
    hunter_p_hit_10k            REAL,
    hunter_burn_10k             REAL,
    hunter_cost_per_hit_10k     REAL,
    hunter_enrich_10k           REAL,
    hunter_p_hit_100k           REAL,
    hunter_burn_100k            REAL,
    hunter_cost_per_hit_100k    REAL,
    hunter_enrich_100k          REAL,
    prof_score                  REAL,
    adj_prof_score              REAL,
    conc_mult                   REAL,
    jp_mult                     REAL,
    wr_mult                     REAL,
    evgw_mult                   REAL,
    verdict                     TEXT,
    detail_url                  TEXT,
    computed_at                 TEXT,
    claim_velocity_base         REAL,
    claim_velocity_top          REAL,
    velocity_divergence         REAL,
    momentum                    REAL,
    win_rate_velocity           REAL,
    days_since_prior            INTEGER,
    momentum_7d                 REAL,
    mom_mult                    REAL,
    UNIQUE(game_number, snapshot_date)
);
CREATE TABLE IF NOT EXISTS csv_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT    NOT NULL,
    game_number     INTEGER,
    game_name       TEXT,
    close_date      TEXT,
    ticket_price    REAL,
    prize_level     TEXT,
    total_prizes    INTEGER,
    prizes_claimed  INTEGER,
    UNIQUE(snapshot_date, game_number, prize_level)
);
"""

# SQL Server DDL — runs as separate statements (no IF NOT EXISTS in CREATE TABLE)
_SQLSRV_DDL = [
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id=OBJECT_ID(N'games_static') AND type=N'U')
    CREATE TABLE games_static (
        game_number             INT PRIMARY KEY,
        pack_size               INT,
        guarantee_per_pack      FLOAT,
        total_tickets_printed   INT,
        overall_odds_launch     FLOAT,
        detail_url              NVARCHAR(500),
        detail_scraped_at       NVARCHAR(60)
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id=OBJECT_ID(N'prize_levels') AND type=N'U')
    CREATE TABLE prize_levels (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        game_number     INT          NOT NULL,
        snapshot_date   NVARCHAR(10) NOT NULL,
        prize_amount    FLOAT        NOT NULL,
        total_printed   INT,
        claimed         INT,
        remaining       INT,
        retention_rate  FLOAT,
        one_in          FLOAT,
        tier            NVARCHAR(20),
        is_jackpot      INT,
        is_meaningful   INT,
        deviation       FLOAT,
        claim_velocity  FLOAT,
        CONSTRAINT UQ_prize_levels UNIQUE (game_number, snapshot_date, prize_amount)
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id=OBJECT_ID(N'games_analysis') AND type=N'U')
    CREATE TABLE games_analysis (
        id                          INT IDENTITY(1,1) PRIMARY KEY,
        game_number                 INT          NOT NULL,
        game_name                   NVARCHAR(200),
        snapshot_date               NVARCHAR(10) NOT NULL,
        close_date                  NVARCHAR(50),
        ticket_price                FLOAT,
        pack_size                   INT,
        guarantee_per_pack          FLOAT,
        pack_cost                   FLOAT,
        max_loss_per_pack           FLOAT,
        total_tickets_printed       INT,
        overall_odds_launch         FLOAT,
        downside_protection         FLOAT,
        sell_through                FLOAT,
        maturity                    FLOAT,
        is_new_game                 INT,
        maturity_confidence         FLOAT,
        remaining_tickets_est       FLOAT,
        total_prizes_printed        INT,
        prizes_claimed              INT,
        prizes_remaining            INT,
        remaining_prize_value       FLOAT,
        ev_per_ticket               FLOAT,
        ev_per_pack                 FLOAT,
        expected_above_guarantee    FLOAT,
        roi_on_max_loss             FLOAT,
        launch_win_rate             FLOAT,
        current_win_rate            FLOAT,
        win_rate_ratio              FLOAT,
        ev_given_win_launch         FLOAT,
        ev_given_win_current        FLOAT,
        ev_given_win_ratio          FLOAT,
        expected_winners_launch     FLOAT,
        expected_winners_current    FLOAT,
        entropy_launch              FLOAT,
        entropy_current             FLOAT,
        entropy_delta               FLOAT,
        n_meaningful_tiers          INT,
        composite_conc              FLOAT,
        concentration_ratio         FLOAT,
        top_bucket_printed          INT,
        top_bucket_remaining        INT,
        jp_amount                   FLOAT,
        jp_printed                  INT,
        jp_remaining                INT,
        jp_conc_ratio               FLOAT,
        p_jp_launch_pack            FLOAT,
        p_jp_curr_pack              FLOAT,
        p_top_launch_pack           FLOAT,
        p_top_curr_pack             FLOAT,
        scenario_p10                FLOAT,
        scenario_p25                FLOAT,
        scenario_p50                FLOAT,
        scenario_p75                FLOAT,
        scenario_p90                FLOAT,
        guarantee_adequacy          FLOAT,
        variance_score              FLOAT,
        p_pack_profit               FLOAT,
        hunter_p_hit_1k             FLOAT,
        hunter_burn_1k              FLOAT,
        hunter_cost_per_hit_1k      FLOAT,
        hunter_enrich_1k            FLOAT,
        hunter_p_hit_10k            FLOAT,
        hunter_burn_10k             FLOAT,
        hunter_cost_per_hit_10k     FLOAT,
        hunter_enrich_10k           FLOAT,
        hunter_p_hit_100k           FLOAT,
        hunter_burn_100k            FLOAT,
        hunter_cost_per_hit_100k    FLOAT,
        hunter_enrich_100k          FLOAT,
        prof_score                  FLOAT,
        adj_prof_score              FLOAT,
        conc_mult                   FLOAT,
        jp_mult                     FLOAT,
        wr_mult                     FLOAT,
        evgw_mult                   FLOAT,
        verdict                     NVARCHAR(30),
        detail_url                  NVARCHAR(500),
        computed_at                 NVARCHAR(60),
        claim_velocity_base         FLOAT,
        claim_velocity_top          FLOAT,
        velocity_divergence         FLOAT,
        momentum                    FLOAT,
        win_rate_velocity           FLOAT,
        days_since_prior            INT,
        momentum_7d                 FLOAT,
        mom_mult                    FLOAT,
        CONSTRAINT UQ_games_analysis UNIQUE (game_number, snapshot_date)
    )
    """,
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id=OBJECT_ID(N'csv_raw') AND type=N'U')
    CREATE TABLE csv_raw (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        snapshot_date   NVARCHAR(10)  NOT NULL,
        game_number     INT,
        game_name       NVARCHAR(200),
        close_date      NVARCHAR(50),
        ticket_price    FLOAT,
        prize_level     NVARCHAR(100),
        total_prizes    INT,
        prizes_claimed  INT,
        CONSTRAINT UQ_csv_raw UNIQUE (snapshot_date, game_number, prize_level)
    )
    """,
]

# Columns to add when upgrading an existing SQLite database
_SQLITE_MIGRATIONS = {
    "games_analysis": [
        ("downside_protection","REAL"), ("sell_through","REAL"), ("maturity_confidence","REAL"),
        ("launch_win_rate","REAL"), ("current_win_rate","REAL"), ("win_rate_ratio","REAL"),
        ("ev_given_win_launch","REAL"), ("ev_given_win_current","REAL"), ("ev_given_win_ratio","REAL"),
        ("expected_winners_launch","REAL"), ("expected_winners_current","REAL"),
        ("entropy_launch","REAL"), ("entropy_current","REAL"), ("entropy_delta","REAL"),
        ("n_meaningful_tiers","INTEGER"), ("composite_conc","REAL"), ("concentration_ratio","REAL"),
        ("top_bucket_printed","INTEGER"), ("top_bucket_remaining","INTEGER"),
        ("jp_amount","REAL"), ("jp_printed","INTEGER"), ("jp_remaining","INTEGER"),
        ("jp_conc_ratio","REAL"), ("p_jp_launch_pack","REAL"), ("p_jp_curr_pack","REAL"),
        ("p_top_launch_pack","REAL"), ("p_top_curr_pack","REAL"),
        ("scenario_p10","REAL"), ("scenario_p25","REAL"), ("scenario_p50","REAL"),
        ("scenario_p75","REAL"), ("scenario_p90","REAL"),
        ("guarantee_adequacy","REAL"), ("variance_score","REAL"),
        ("p_pack_profit","REAL"),
        ("hunter_p_hit_1k","REAL"), ("hunter_burn_1k","REAL"),
        ("hunter_cost_per_hit_1k","REAL"), ("hunter_enrich_1k","REAL"),
        ("hunter_p_hit_10k","REAL"), ("hunter_burn_10k","REAL"),
        ("hunter_cost_per_hit_10k","REAL"), ("hunter_enrich_10k","REAL"),
        ("hunter_p_hit_100k","REAL"), ("hunter_burn_100k","REAL"),
        ("hunter_cost_per_hit_100k","REAL"), ("hunter_enrich_100k","REAL"),
        ("prof_score","REAL"), ("adj_prof_score","REAL"),
        ("conc_mult","REAL"), ("jp_mult","REAL"), ("wr_mult","REAL"), ("evgw_mult","REAL"),
        ("verdict","TEXT"),
        ("claim_velocity_base","REAL"), ("claim_velocity_top","REAL"),
        ("velocity_divergence","REAL"), ("momentum","REAL"),
        ("win_rate_velocity","REAL"), ("days_since_prior","INTEGER"),
        ("momentum_7d","REAL"), ("mom_mult","REAL"),
    ],
    "prize_levels": [
        ("one_in","REAL"), ("tier","TEXT"), ("is_jackpot","INTEGER"),
        ("is_meaningful","INTEGER"), ("deviation","REAL"),
        ("claim_velocity","REAL"),
    ],
}

# New columns to add to SQL Server when upgrading schema
_SQLSRV_MIGRATIONS = {
    "games_analysis": [
        ("downside_protection","FLOAT"), ("sell_through","FLOAT"), ("maturity_confidence","FLOAT"),
        ("launch_win_rate","FLOAT"), ("current_win_rate","FLOAT"), ("win_rate_ratio","FLOAT"),
        ("ev_given_win_launch","FLOAT"), ("ev_given_win_current","FLOAT"), ("ev_given_win_ratio","FLOAT"),
        ("expected_winners_launch","FLOAT"), ("expected_winners_current","FLOAT"),
        ("entropy_launch","FLOAT"), ("entropy_current","FLOAT"), ("entropy_delta","FLOAT"),
        ("n_meaningful_tiers","INT"), ("composite_conc","FLOAT"), ("concentration_ratio","FLOAT"),
        ("top_bucket_printed","INT"), ("top_bucket_remaining","INT"),
        ("jp_amount","FLOAT"), ("jp_printed","INT"), ("jp_remaining","INT"),
        ("jp_conc_ratio","FLOAT"), ("p_jp_launch_pack","FLOAT"), ("p_jp_curr_pack","FLOAT"),
        ("p_top_launch_pack","FLOAT"), ("p_top_curr_pack","FLOAT"),
        ("scenario_p10","FLOAT"), ("scenario_p25","FLOAT"), ("scenario_p50","FLOAT"),
        ("scenario_p75","FLOAT"), ("scenario_p90","FLOAT"),
        ("guarantee_adequacy","FLOAT"), ("variance_score","FLOAT"),
        ("p_pack_profit","FLOAT"),
        ("hunter_p_hit_1k","FLOAT"), ("hunter_burn_1k","FLOAT"),
        ("hunter_cost_per_hit_1k","FLOAT"), ("hunter_enrich_1k","FLOAT"),
        ("hunter_p_hit_10k","FLOAT"), ("hunter_burn_10k","FLOAT"),
        ("hunter_cost_per_hit_10k","FLOAT"), ("hunter_enrich_10k","FLOAT"),
        ("hunter_p_hit_100k","FLOAT"), ("hunter_burn_100k","FLOAT"),
        ("hunter_cost_per_hit_100k","FLOAT"), ("hunter_enrich_100k","FLOAT"),
        ("prof_score","FLOAT"), ("adj_prof_score","FLOAT"),
        ("conc_mult","FLOAT"), ("jp_mult","FLOAT"), ("wr_mult","FLOAT"), ("evgw_mult","FLOAT"),
        ("verdict","NVARCHAR(30)"),
        ("claim_velocity_base","FLOAT"), ("claim_velocity_top","FLOAT"),
        ("velocity_divergence","FLOAT"), ("momentum","FLOAT"),
        ("win_rate_velocity","FLOAT"), ("days_since_prior","INT"),
        ("momentum_7d","FLOAT"), ("mom_mult","FLOAT"),
    ],
    "prize_levels": [
        ("one_in","FLOAT"), ("tier","NVARCHAR(20)"), ("is_jackpot","INT"),
        ("is_meaningful","INT"), ("deviation","FLOAT"),
        ("claim_velocity","FLOAT"),
    ],
}


class Database:
    """Thin wrapper supporting SQL Server (default) and SQLite."""

    def __init__(self, mode: str = "sqlserver"):
        self.mode = mode

        if mode == "sqlite":
            path = CONFIG["sqlite_path"]
            log.info(f"Using SQLite: {path}")
            self.conn = sqlite3.connect(path)
            self.conn.executescript(_SQLITE_DDL)
            self.conn.commit()
            self._migrate_sqlite()
        else:
            import pyodbc
            cfg = CONFIG["sql_server"]
            if not cfg["pwd"]:
                raise RuntimeError("TXLOTTERY_PWD env var not set")
            pwd_escaped = cfg["pwd"].replace("}", "}}")
            cs = (
                f"DRIVER={cfg['driver']};"
                f"SERVER={cfg['server']};"
                f"DATABASE={cfg['database']};"
                f"UID={cfg['uid']};"
                f"PWD={{{pwd_escaped}}};"
                f"Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30;"
            )
            log.info(f"Connecting to SQL Server: {cfg['server']} / {cfg['database']}")
            self.conn = pyodbc.connect(cs)
            self.conn.autocommit = False
            self._ensure_schema_sqlserver()
            self._migrate_sqlserver()

    # ── Schema creation ────────────────────────────────────────────────────────

    def _ensure_schema_sqlserver(self):
        cur = self.conn.cursor()
        for stmt in _SQLSRV_DDL:
            cur.execute(stmt)
        self.conn.commit()
        log.info("SQL Server schema verified.")

    def _migrate_sqlite(self):
        for table, cols in _SQLITE_MIGRATIONS.items():
            for col, typ in cols:
                try:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass
        self.conn.commit()

    def _migrate_sqlserver(self):
        cur = self.conn.cursor()
        for table, cols in _SQLSRV_MIGRATIONS.items():
            for col, typ in cols:
                cur.execute(f"""
                    IF NOT EXISTS (
                        SELECT * FROM sys.columns
                        WHERE object_id=OBJECT_ID(N'{table}') AND name=N'{col}'
                    )
                    ALTER TABLE {table} ADD {col} {typ}
                """)
        self.conn.commit()

    # ── Sort helpers (SQL Server has no NULLS LAST / LIMIT) ───────────────────

    def _score_order(self) -> str:
        if self.mode == "sqlserver":
            return "CASE WHEN adj_prof_score IS NULL THEN 1 ELSE 0 END, adj_prof_score DESC"
        return "adj_prof_score DESC NULLS LAST"

    def _top_n(self, n: int) -> str:
        return f"TOP {n}" if self.mode == "sqlserver" else ""

    def _limit_n(self, n: int) -> str:
        return "" if self.mode == "sqlserver" else f"LIMIT {n}"

    # ── Upserts ───────────────────────────────────────────────────────────────

    def upsert_static(self, detail: dict):
        keys = ["game_number","pack_size","guarantee_per_pack",
                "total_tickets_printed","overall_odds_launch",
                "detail_url","detail_scraped_at"]
        vals = [detail.get(k) for k in keys]

        if self.mode == "sqlite":
            self.conn.execute(
                f"INSERT OR REPLACE INTO games_static ({','.join(keys)}) "
                f"VALUES ({','.join(['?']*len(keys))})",
                vals,
            )
            self.conn.commit()
        else:
            cur = self.conn.cursor()
            cur.execute("""
                MERGE games_static AS t
                USING (SELECT ? AS game_number) AS s ON t.game_number=s.game_number
                WHEN MATCHED THEN UPDATE SET
                    pack_size=?,guarantee_per_pack=?,total_tickets_printed=?,
                    overall_odds_launch=?,detail_url=?,detail_scraped_at=?
                WHEN NOT MATCHED THEN INSERT
                    (game_number,pack_size,guarantee_per_pack,total_tickets_printed,
                     overall_odds_launch,detail_url,detail_scraped_at)
                    VALUES (?,?,?,?,?,?,?);
            """, [vals[0]] + vals[1:] + vals)
            self.conn.commit()

    def upsert_prize_levels(self, game_number: int, snapshot_date: str, levels: list[dict]):
        if self.mode == "sqlite":
            for lv in levels:
                self.conn.execute(
                    "INSERT OR REPLACE INTO prize_levels "
                    "(game_number,snapshot_date,prize_amount,total_printed,claimed,remaining,"
                    "retention_rate,one_in,tier,is_jackpot,is_meaningful,deviation,claim_velocity) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [game_number, snapshot_date, lv["amount"], lv["total"],
                     lv["claimed"], lv["remaining"], lv["retention_rate"],
                     lv.get("one_in"), lv.get("tier"),
                     int(lv.get("is_jackpot", False)),
                     int(lv.get("is_meaningful", False)),
                     lv.get("deviation"), lv.get("claim_velocity")],
                )
            self.conn.commit()
        else:
            cur = self.conn.cursor()
            for lv in levels:
                cur.execute("""
                    MERGE prize_levels AS t
                    USING (SELECT ? AS game_number, ? AS snapshot_date, ? AS prize_amount) AS s
                        ON t.game_number=s.game_number
                       AND t.snapshot_date=s.snapshot_date
                       AND t.prize_amount=s.prize_amount
                    WHEN MATCHED THEN UPDATE SET
                        total_printed=?,claimed=?,remaining=?,retention_rate=?,
                        one_in=?,tier=?,is_jackpot=?,is_meaningful=?,deviation=?,
                        claim_velocity=?
                    WHEN NOT MATCHED THEN INSERT
                        (game_number,snapshot_date,prize_amount,total_printed,claimed,
                         remaining,retention_rate,one_in,tier,is_jackpot,is_meaningful,
                         deviation,claim_velocity)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?);
                """, [
                    game_number, snapshot_date, lv["amount"],          # USING key
                    lv["total"], lv["claimed"], lv["remaining"],        # UPDATE
                    lv["retention_rate"], lv.get("one_in"),
                    lv.get("tier"),
                    int(lv.get("is_jackpot", False)),
                    int(lv.get("is_meaningful", False)),
                    lv.get("deviation"), lv.get("claim_velocity"),
                    game_number, snapshot_date, lv["amount"],           # INSERT
                    lv["total"], lv["claimed"], lv["remaining"],
                    lv["retention_rate"], lv.get("one_in"),
                    lv.get("tier"),
                    int(lv.get("is_jackpot", False)),
                    int(lv.get("is_meaningful", False)),
                    lv.get("deviation"), lv.get("claim_velocity"),
                ])
            self.conn.commit()

    def upsert_csv_raw(self, rows: list[dict], snapshot_date: str):
        """Store the raw parsed CSV rows (including TOTAL rows) unchanged."""
        if self.mode == "sqlite":
            for r in rows:
                self.conn.execute(
                    "INSERT OR REPLACE INTO csv_raw "
                    "(snapshot_date,game_number,game_name,close_date,ticket_price,"
                    "prize_level,total_prizes,prizes_claimed) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [snapshot_date, r["game_number"], r["game_name"], r.get("close_date"),
                     r["ticket_price"], r["prize_level"], r["total_prizes"], r["prizes_claimed"]],
                )
            self.conn.commit()
        else:
            cur = self.conn.cursor()
            for r in rows:
                cur.execute("""
                    MERGE csv_raw AS t
                    USING (SELECT ? AS snapshot_date, ? AS game_number, ? AS prize_level) AS s
                        ON t.snapshot_date=s.snapshot_date
                       AND t.game_number=s.game_number
                       AND t.prize_level=s.prize_level
                    WHEN MATCHED THEN UPDATE SET
                        game_name=?,close_date=?,ticket_price=?,
                        total_prizes=?,prizes_claimed=?
                    WHEN NOT MATCHED THEN INSERT
                        (snapshot_date,game_number,prize_level,game_name,close_date,
                         ticket_price,total_prizes,prizes_claimed)
                        VALUES (?,?,?,?,?,?,?,?);
                """, [
                    snapshot_date, r["game_number"], r["prize_level"],   # USING key
                    r["game_name"], r.get("close_date"), r["ticket_price"],  # UPDATE
                    r["total_prizes"], r["prizes_claimed"],
                    snapshot_date, r["game_number"], r["prize_level"],   # INSERT
                    r["game_name"], r.get("close_date"), r["ticket_price"],
                    r["total_prizes"], r["prizes_claimed"],
                ])
            self.conn.commit()
        log.info(f"  csv_raw: {len(rows)} rows staged for {snapshot_date}")

    def upsert_analysis(self, rec: dict):
        keys = list(rec.keys())
        vals = list(rec.values())

        if self.mode == "sqlite":
            self.conn.execute(
                f"INSERT OR REPLACE INTO games_analysis ({','.join(keys)}) "
                f"VALUES ({','.join(['?']*len(keys))})",
                vals,
            )
            self.conn.commit()
        else:
            non_key_cols = [k for k in keys if k not in ("game_number","snapshot_date")]
            set_clause   = ", ".join(f"{k}=?" for k in non_key_cols)
            set_vals     = [rec[k] for k in non_key_cols]
            cur = self.conn.cursor()
            cur.execute(f"""
                MERGE games_analysis AS t
                USING (SELECT ? AS game_number, ? AS snapshot_date) AS s
                    ON t.game_number=s.game_number AND t.snapshot_date=s.snapshot_date
                WHEN MATCHED THEN UPDATE SET {set_clause}
                WHEN NOT MATCHED THEN INSERT ({','.join(keys)}) VALUES ({','.join(['?']*len(keys))});
            """, [rec["game_number"], rec["snapshot_date"]] + set_vals + vals)
            self.conn.commit()

    # ── Reads ──────────────────────────────────────────────────────────────────

    def load_static(self) -> dict[int, dict]:
        cur  = self.conn.execute("SELECT * FROM games_static")
        cols = [d[0] for d in cur.description]
        return {row[0]: dict(zip(cols, row)) for row in cur.fetchall()}

    def fetch_rows(self, sql: str, params: tuple = ()) -> tuple[list[str], list]:
        cur  = self.conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return cols, cur.fetchall()

    def close(self):
        self.conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT / PRINT LAYER
# ══════════════════════════════════════════════════════════════════════════════

def export_json(db: Database, out_path: Path, snapshot_date: str = None):
    today = snapshot_date or date.today().isoformat()
    cols, rows = db.fetch_rows(
        f"SELECT * FROM games_analysis WHERE snapshot_date=? "
        f"ORDER BY {db._score_order()}",
        (today,)
    )
    games = [dict(zip(cols, r)) for r in rows]

    cols2, rows2 = db.fetch_rows(
        "SELECT * FROM prize_levels WHERE snapshot_date=?", (today,)
    )
    levels_by_game: dict[int, list] = defaultdict(list)
    for row in rows2:
        d = dict(zip(cols2, row))
        levels_by_game[d["game_number"]].append({
            "amount":       d["prize_amount"],
            "total":        d["total_printed"],
            "claimed":      d["claimed"],
            "remaining":    d["remaining"],
            "retention":    d["retention_rate"],
            "one_in":       d.get("one_in"),
            "tier":         d.get("tier"),
            "is_meaningful":bool(d.get("is_meaningful")),
            "is_jackpot":   bool(d.get("is_jackpot")),
            "deviation":    d.get("deviation"),
        })

    score_max = None
    for game in games:
        pls = sorted(levels_by_game.get(game["game_number"], []),
                     key=lambda p: p["amount"])
        game["prize_levels"] = pls
        s = game.get("adj_prof_score")
        if s is not None and (score_max is None or s > score_max):
            score_max = s

    payload = {
        "asOf":        today,
        "generatedAt": datetime.now(timezone.utc).isoformat() + "Z",
        "gameCount":   len(games),
        "score_max":   score_max,
        "games":       games,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    log.info(f"Exported JSON: {out_path}  ({len(games)} games, score_max={score_max})")


def export_csv(db: Database, out_path: Path, snapshot_date: str = None):
    today = snapshot_date or date.today().isoformat()
    cols, rows = db.fetch_rows(
        f"SELECT * FROM games_analysis WHERE snapshot_date=? ORDER BY {db._score_order()}",
        (today,)
    )
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    log.info(f"Exported {len(rows)} rows to {out_path}")


def print_top_games(db: Database, snapshot_date: str = None, n: int = 15):
    today = snapshot_date or date.today().isoformat()
    top   = db._top_n(n)
    lim   = db._limit_n(n)
    cols, rows = db.fetch_rows(f"""
        SELECT {top} game_number, game_name, ticket_price, pack_cost, max_loss_per_pack,
               guarantee_per_pack, ev_per_pack, roi_on_max_loss,
               maturity, adj_prof_score, verdict,
               jp_amount, jp_remaining, win_rate_ratio, composite_conc
        FROM games_analysis
        WHERE snapshot_date=? AND verdict NOT IN ('no_data','too_new','_pending')
        ORDER BY {db._score_order()}
        {lim}
    """, (today,))

    if not rows:
        log.warning("No scored analysis rows found for this snapshot.")
        return

    print(f"\n{'-'*130}")
    print(f"  TOP {n} GAMES  |  Snapshot: {today}"
          + ("  [numpy]" if _HAS_NUMPY else "  [pure-python MC]"))
    print(f"{'-'*130}")
    hdr = (f"{'#':>3}  {'Game':30}  {'$':>4}  {'Pack$':>5}  {'MaxLoss':>7}  "
           f"{'ROI%':>6}  {'Mature':>6}  {'WinRate':>7}  {'Conc':>6}  "
           f"{'Score':>7}  {'Verdict':12}  {'TopPrize':>12}  {'Left':>5}")
    print(hdr)
    print(f"{'-'*130}")

    for i, r in enumerate(rows, 1):
        (gnum, gname, price, pack_cost, max_loss, guarantee, ev_pack,
         roi, maturity, score, verdict,
         jp_amt, jp_rem, wr_ratio, conc) = r

        roi_str  = f"{roi*100:5.1f}%" if roi      is not None else "   n/a"
        ml_str   = f"${max_loss:.0f}" if max_loss  is not None else "  n/a"
        pc_str   = f"${pack_cost:.0f}"if pack_cost is not None else "  n/a"
        sc_str   = f"{score:.4f}"     if score     is not None else "   n/a"
        top_str  = f"${jp_amt:,.0f}"  if jp_amt    is not None else "    n/a"
        rem_str  = str(int(jp_rem))   if jp_rem    is not None else "  n/a"
        wr_str   = f"{wr_ratio:.3f}x" if wr_ratio  is not None else "    n/a"
        conc_str = f"{conc:.3f}"      if conc      is not None else "   n/a"
        v_str    = (verdict or "").replace("_", " ")

        print(
            f"  {i:>2}.  {gname[:30]:30}  ${price:>3.0f}  {pc_str:>5}  {ml_str:>7}  "
            f"{roi_str:>6}  {maturity:>5.1%}  {wr_str:>7}  {conc_str:>6}  "
            f"{sc_str:>7}  {v_str:12}  {top_str:>12}  {rem_str:>5}"
        )
    print(f"{'-'*130}\n")


# ══════════════════════════════════════════════════════════════════════════════
# RECOMPUTE
# ══════════════════════════════════════════════════════════════════════════════

def run_recompute(db: Database):
    existing_static = db.load_static()

    _, rows = db.fetch_rows("""
        SELECT DISTINCT pl.game_number, pl.snapshot_date,
               ga.game_name, ga.close_date, ga.ticket_price,
               ga.total_prizes_printed, ga.prizes_claimed
        FROM prize_levels pl
        LEFT JOIN games_analysis ga
          ON pl.game_number=ga.game_number AND pl.snapshot_date=ga.snapshot_date
        ORDER BY pl.snapshot_date, pl.game_number
    """)

    by_date: dict[str, list] = defaultdict(list)
    for row in rows:
        by_date[row[1]].append(row)

    for snap_date in sorted(by_date):
        date_rows = by_date[snap_date]
        log.info(f"Recomputing {len(date_rows)} games for {snap_date}...")
        all_recs = []
        all_levels_map = {}

        for (gnum, sdate, gname, close_date, ticket_price, total_prizes, claimed) in date_rows:
            _, lvl_rows = db.fetch_rows(
                "SELECT prize_amount, total_printed, claimed FROM prize_levels "
                "WHERE game_number=? AND snapshot_date=? ORDER BY prize_amount ASC",
                (gnum, sdate),
            )
            prize_levels = [{"amount": r[0], "total": r[1], "claimed": r[2]} for r in lvl_rows]
            if not prize_levels:
                continue

            total_p   = total_prizes or sum(p["total"]   for p in prize_levels)
            claimed_p = claimed      or sum(p["claimed"] for p in prize_levels)

            game = {
                "game_number":   gnum,
                "game_name":     gname or f"Game #{gnum}",
                "close_date":    close_date,
                "ticket_price":  ticket_price or 0.0,
                "snapshot_date": sdate,
                "prize_levels":  prize_levels,
                "total_prizes":  total_p,
                "claimed_prizes":claimed_p,
            }
            detail = existing_static.get(gnum, {})
            rec    = compute_analytics(game, detail)
            enriched_levels = rec.pop("_levels")
            all_recs.append(rec)
            all_levels_map[gnum] = enriched_levels

        compute_velocity_metrics(db, all_recs, all_levels_map, snap_date)
        assign_verdicts(all_recs)
        for rec in all_recs:
            db.upsert_prize_levels(rec["game_number"], snap_date, all_levels_map[rec["game_number"]])
            db.upsert_analysis(rec)

        log.info(f"  {snap_date}: done.")

    log.info("Recompute complete.")


# ══════════════════════════════════════════════════════════════════════════════
# SQLITE → SQL SERVER MIGRATION
# ══════════════════════════════════════════════════════════════════════════════

def migrate_sqlite_to_sqlserver(sqlite_path: Path, sqlsrv_db: Database):
    """Copy all data from a local SQLite file into the SQL Server database."""
    if not sqlite_path.exists():
        log.error(f"SQLite file not found: {sqlite_path}")
        return

    log.info(f"Migrating {sqlite_path} -> SQL Server...")
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    # games_static
    rows = src.execute("SELECT * FROM games_static").fetchall()
    log.info(f"  games_static: {len(rows)} rows")
    for row in rows:
        sqlsrv_db.upsert_static(dict(row))

    # prize_levels — batch by snapshot for logging
    snap_dates = [r[0] for r in src.execute(
        "SELECT DISTINCT snapshot_date FROM prize_levels ORDER BY snapshot_date").fetchall()]
    for sd in snap_dates:
        rows = src.execute(
            "SELECT game_number, prize_amount, total_printed, claimed, remaining, "
            "retention_rate, one_in, tier, is_jackpot, is_meaningful, deviation "
            "FROM prize_levels WHERE snapshot_date=?", (sd,)
        ).fetchall()
        by_game: dict[int, list] = defaultdict(list)
        for r in rows:
            by_game[r[0]].append({
                "amount": r[1], "total": r[2], "claimed": r[3],
                "remaining": r[4], "retention_rate": r[5],
                "one_in": r[6], "tier": r[7],
                "is_jackpot": r[8], "is_meaningful": r[9], "deviation": r[10],
            })
        for gnum, levels in by_game.items():
            sqlsrv_db.upsert_prize_levels(gnum, sd, levels)
        log.info(f"  prize_levels {sd}: {len(rows)} rows across {len(by_game)} games")

    # games_analysis
    for sd in snap_dates:
        cols_cur = src.execute("SELECT * FROM games_analysis WHERE snapshot_date=? LIMIT 1", (sd,))
        if cols_cur.description is None:
            continue
        col_names = [d[0] for d in cols_cur.description]
        rows = src.execute("SELECT * FROM games_analysis WHERE snapshot_date=?", (sd,)).fetchall()
        # Only keep columns that exist in the SQL Server schema
        sqlsrv_cols = {c[0] for c in sqlsrv_db.conn.execute(
            "SELECT name FROM sys.columns WHERE object_id=OBJECT_ID(N'games_analysis')"
        ).fetchall()}
        for row in rows:
            rec = {k: v for k, v in dict(zip(col_names, row)).items()
                   if k in sqlsrv_cols and k not in ("id",)}
            sqlsrv_db.upsert_analysis(rec)
        log.info(f"  games_analysis {sd}: {len(rows)} rows")

    src.close()
    log.info("Migration complete.")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def run(args):
    db_mode = getattr(args, "db", "sqlserver")
    db      = Database(db_mode)
    session = requests.Session()

    if getattr(args, "migrate_sqlite", False):
        migrate_sqlite_to_sqlserver(CONFIG["sqlite_path"], db)
        db.close()
        return

    if getattr(args, "recompute", False):
        run_recompute(db)
        _, row = db.fetch_rows(
            "SELECT snapshot_date FROM games_analysis ORDER BY snapshot_date DESC", ()
        )
        if row:
            json_path = Path(__file__).parent / "tx_lottery_latest.json"
            export_json(db, json_path, row[0][0])
        db.close()
        log.info("Done.")
        return

    # ── 1. Fetch CSV ──────────────────────────────────────────────────────────
    csv_rows, snapshot_date = fetch_csv(session)
    if not snapshot_date:
        snapshot_date = date.today().isoformat()

    db.upsert_csv_raw(csv_rows, snapshot_date)

    game_records = build_game_records(csv_rows, snapshot_date)
    game_numbers = sorted(game_records.keys())
    log.info(f"Games in CSV: {len(game_numbers)}")

    # ── 2. Load existing static detail data ───────────────────────────────────
    existing_static = db.load_static()
    log.info(f"Games with static data cached: {len(existing_static)}")

    # ── 3. Fetch detail pages (bootstrap or new games only) ───────────────────
    if not args.daily_only:
        detail_urls = fetch_detail_urls(session)
        new_games   = [n for n in game_numbers if n not in existing_static]
        if new_games or args.bootstrap:
            target = game_numbers if args.bootstrap else new_games
            log.info(f"Fetching detail pages for {len(target)} game(s)...")
            all_details = fetch_all_details(
                target, detail_urls, existing_static, session,
                force=args.bootstrap,
            )
            for gnum, detail in all_details.items():
                if detail.get("pack_size"):
                    db.upsert_static(detail)
            existing_static = db.load_static()
        else:
            log.info("No new games detected - skipping detail page fetch.")

    # ── 4. Compute analytics ──────────────────────────────────────────────────
    log.info("Computing analytics...")
    all_recs       = []
    all_levels_map = {}

    for gnum, game in game_records.items():
        detail = existing_static.get(gnum, {})
        rec    = compute_analytics(game, detail)
        enriched_levels = rec.pop("_levels")
        all_recs.append(rec)
        all_levels_map[gnum] = enriched_levels

    # ── 5. Velocity metrics + momentum multiplier (must precede verdicts) ────
    compute_velocity_metrics(db, all_recs, all_levels_map, snapshot_date)

    # ── 5b. Assign percentile-based verdicts on momentum-adjusted scores ─────
    assign_verdicts(all_recs)

    # ── 6. Write to database ──────────────────────────────────────────────────
    for rec in all_recs:
        gnum = rec["game_number"]
        db.upsert_prize_levels(gnum, snapshot_date, all_levels_map[gnum])
        db.upsert_analysis(rec)

    scored    = [r for r in all_recs if r.get("adj_prof_score") is not None]
    score_max = max((r["adj_prof_score"] for r in scored), default=None)
    log.info(
        f"Analytics staged: {len(all_recs)} games  scored: {len(scored)}  "
        f"score_max: {score_max:.4f}" if score_max else
        f"Analytics staged: {len(all_recs)} games."
    )

    # ── 7. Output ─────────────────────────────────────────────────────────────
    print_top_games(db, snapshot_date)

    json_path = Path(__file__).parent / "tx_lottery_latest.json"
    export_json(db, json_path, snapshot_date)

    if args.export_csv:
        out = Path(__file__).parent / f"tx_lottery_analysis_{snapshot_date}.csv"
        export_csv(db, out, snapshot_date)

    db.close()
    log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TX Lottery daily scraper and analytics pipeline.")
    parser.add_argument("--bootstrap",      action="store_true", help="Re-fetch ALL detail pages")
    parser.add_argument("--daily-only",     action="store_true", help="Skip detail page fetch")
    parser.add_argument("--recompute",      action="store_true", help="Recompute analytics for all snapshots")
    parser.add_argument("--export-csv",     action="store_true", help="Export analysis to CSV after run")
    parser.add_argument("--migrate-sqlite", action="store_true", help="One-time copy of local SQLite into SQL Server")
    parser.add_argument("--db", choices=["sqlite","sqlserver"], default="sqlserver",
                        help="Database backend (default: sqlserver)")
    args = parser.parse_args()
    run(args)
