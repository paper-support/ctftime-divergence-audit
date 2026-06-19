#!/usr/bin/env python3
"""CTFtime API collection — Phases 1 and 2.

Phase 1 (~50 min): events list (monthly windows) + results/top/top-by-country/votes per year.
Phase 2 (~14–28 hr): individual /teams/{id}/ for a filtered subset.

Fully resumable: existing files are skipped. Provenance sidecars written.

Usage:
    python3 collect_api.py phase1
    python3 collect_api.py phase2 [--top-n 500]
    python3 collect_api.py summary           # report what's been collected so far
"""
from __future__ import annotations

import argparse
import json
import sys
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path

from utils import (
    DATA_RAW,
    PoliteClient,
    already_have,
    atomic_write_json,
    setup_logging,
)

API_ROOT = "https://ctftime.org/api/v1"
START_YEAR = 2011
END_YEAR = 2026  # inclusive

# Manually curated list — major CTF-active countries. Extend as needed.
# ISO-3166-1 alpha-2 lowercase as required by /top-by-country/{cc}/.
COUNTRIES = [
    "us", "ru", "cn", "kr", "de", "fr", "gb", "jp", "in", "br",
    "pl", "ua", "tw", "vn", "il", "se", "fi", "no", "dk", "nl",
    "be", "es", "it", "tr", "ca", "au", "sg", "hk", "ch", "at",
    "cz", "ee", "lv", "lt", "ro", "bg", "gr", "pt", "ie", "mx",
    "ar", "cl", "co", "id", "th", "my", "ph", "za", "eg", "sa",
]

logger = setup_logging("collect_api")


# ------------------------------------------------------------------ Phase 1 ---

def collect_events(client: PoliteClient, only_year: int | None = None) -> int:
    """Pull every CTFtime event 2011-01 → END_YEAR-12, one call per month-window.

    The /events/?start&finish endpoint returns full event detail in the list response
    (description, weight, organizers, etc.) so no per-event detail call is needed.
    """
    n_new = 0
    years = [only_year] if only_year else range(START_YEAR, END_YEAR + 1)
    for year in years:
        for month in range(1, 13):
            out = DATA_RAW / "api" / "events" / f"{year:04d}-{month:02d}.json"
            if already_have(out):
                continue
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            last_day = monthrange(year, month)[1]
            finish = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
            params = {
                "limit": 1000,  # overshoot — CTFtime caps internally if smaller
                "start": int(start.timestamp()),
                "finish": int(finish.timestamp()),
            }
            url = f"{API_ROOT}/events/"
            data = client.get_json(url, params=params)
            wrote = atomic_write_json(out, data, f"{url}?start={params['start']}&finish={params['finish']}")
            if wrote:
                n_new += 1
                logger.info(f"events {year}-{month:02d}: {len(data)} events → {out.name}")
    return n_new


def collect_yearly(client: PoliteClient, sub: str, ext_url: str, only_year: int | None = None) -> int:
    """Collect /<sub>/{year}/ for every year. Used for results, top, votes."""
    n_new = 0
    years = [only_year] if only_year else range(START_YEAR, END_YEAR + 1)
    for year in years:
        out = DATA_RAW / "api" / sub / f"{year}.json"
        if already_have(out):
            continue
        url = f"{API_ROOT}/{ext_url}/{year}/"
        params = {"limit": 10000} if sub == "top" else None
        try:
            data = client.get_json(url, params=params)
        except Exception as e:
            logger.warning(f"{sub} {year}: failed ({e}) — writing empty placeholder")
            data = {"_error": str(e), "_year": year}
        wrote = atomic_write_json(out, data, url + (f"?limit={params['limit']}" if params else ""))
        if wrote:
            n_new += 1
            logger.info(f"{sub} {year}: → {out.name}")
    return n_new


def collect_top_by_country(client: PoliteClient) -> int:
    n_new = 0
    for cc in COUNTRIES:
        out = DATA_RAW / "api" / "top_by_country" / f"{cc}.json"
        if already_have(out):
            continue
        url = f"{API_ROOT}/top-by-country/{cc}/"
        try:
            data = client.get_json(url)
        except Exception as e:
            logger.warning(f"top-by-country {cc}: failed ({e})")
            data = {"_error": str(e), "_country": cc}
        wrote = atomic_write_json(out, data, url)
        if wrote:
            n_new += 1
            logger.info(f"top-by-country {cc}: → {out.name}")
    return n_new


def phase1(only_year: int | None = None, skip_country: bool = False):
    client = PoliteClient()
    try:
        new = 0
        new += collect_events(client, only_year=only_year)
        new += collect_yearly(client, sub="results", ext_url="results", only_year=only_year)
        new += collect_yearly(client, sub="top", ext_url="top", only_year=only_year)
        new += collect_yearly(client, sub="votes", ext_url="votes", only_year=only_year)
        if not skip_country:
            new += collect_top_by_country(client)
        scope = f"year={only_year}" if only_year else "all years"
        logger.info(f"Phase 1 complete ({scope}) — {new} new files written.")
    finally:
        client.close()


# ------------------------------------------------------------------ Phase 1b --

def collect_teams_paginated(client: PoliteClient, page_size: int = 200) -> int:
    """Walk /api/v1/teams/?limit=N&offset=M to enumerate the full team registry.

    Each page returns {limit, offset, result: [...]} with id/name/country/academic/
    aliases per team. Stops when result is empty.

    Saves one file per offset window: data/raw/api/teams_index/p{offset:08d}.json
    """
    out_dir = DATA_RAW / "api" / "teams_index"
    out_dir.mkdir(parents=True, exist_ok=True)
    n_new = 0
    offset = 0
    # resume from highest offset already on disk
    existing = sorted(int(p.stem.lstrip("p")) for p in out_dir.glob("p*.json"))
    if existing:
        offset = existing[-1] + page_size
        logger.info(f"phase1b resume — continuing from offset {offset}")
    consecutive_empty = 0
    while True:
        out = out_dir / f"p{offset:08d}.json"
        if already_have(out):
            offset += page_size
            continue
        url = f"{API_ROOT}/teams/"
        params = {"limit": page_size, "offset": offset}
        data = client.get_json(url, params=params)
        if isinstance(data, dict):
            result = data.get("result") or []
        else:
            result = data if isinstance(data, list) else []
        atomic_write_json(out, data, f"{url}?limit={page_size}&offset={offset}")
        n_new += 1
        logger.info(f"teams_index offset={offset}: {len(result)} teams")
        if not result:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                logger.info("two empty pages in a row — assuming end of registry")
                break
        else:
            consecutive_empty = 0
        offset += page_size
    return n_new


def phase1b(page_size: int = 200):
    """Full team enumeration via paginated API."""
    client = PoliteClient()
    try:
        n = collect_teams_paginated(client, page_size=page_size)
        logger.info(f"Phase 1b complete — {n} new index pages.")
    finally:
        client.close()


# ------------------------------------------------------------------ Phase 2 ---

def collect_team(client: PoliteClient, team_id: int) -> bool:
    out = DATA_RAW / "api" / "teams" / f"{team_id}.json"
    if already_have(out):
        return False
    url = f"{API_ROOT}/teams/{team_id}/"
    try:
        data = client.get_json(url)
    except Exception as e:
        logger.warning(f"team {team_id}: failed ({e})")
        return False
    return atomic_write_json(out, data, url)


def discover_team_ids(top_n_per_year: int = 100,
                      min_events: int = 10,
                      min_active_years: int = 3,
                      include_academic: bool = True) -> set[int]:
    """Tier-1 sampling per Codex round 5: union of
       (academic_flag) ∪ (top-N per year) ∪ (≥min_events events) ∪ (≥min_active_years years)

    NOT the full registry — full-registry detail fetch is infeasible
    (333K teams × 5 s ≈ 19 days). Tier-1 covers ~34 K teams, ~47 hr at 5 s.
    """
    from collections import Counter, defaultdict
    ids: set[int] = set()

    # 1. Academic-flagged from teams_index
    if include_academic:
        for p in (DATA_RAW / "api" / "teams_index").glob("*.json"):
            if p.name.endswith(".meta.json"): continue
            d = json.loads(p.read_text())
            for r in d.get("result", []):
                if isinstance(r, dict) and r.get("academic") and "id" in r:
                    ids.add(int(r["id"]))

    # 2. Top-N per year from /api/v1/top/{year}/  (capped at 100 server-side)
    for p in (DATA_RAW / "api" / "top").glob("*.json"):
        if p.name.endswith(".meta.json"): continue
        d = json.loads(p.read_text())
        for rows in d.values() if isinstance(d, dict) else []:
            if not isinstance(rows, list): continue
            for r in rows[:top_n_per_year]:
                if isinstance(r, dict) and "team_id" in r:
                    ids.add(int(r["team_id"]))

    # 3. Activity-based: aggregate /results/ into per-team event count + active-year set
    team_events: Counter = Counter()
    team_years: dict[int, set] = defaultdict(set)
    for p in (DATA_RAW / "api" / "results").glob("*.json"):
        if p.name.endswith(".meta.json"): continue
        yr = p.stem
        d = json.loads(p.read_text())
        if not isinstance(d, dict): continue
        for ev in d.values():
            for s in ev.get("scores", []):
                tid = s.get("team_id")
                if tid:
                    team_events[tid] += 1
                    team_years[tid].add(yr)
    ids |= {tid for tid, c in team_events.items() if c >= min_events}
    ids |= {tid for tid, ys in team_years.items() if len(ys) >= min_active_years}

    return ids
    # From /top/{year}/
    for year in range(START_YEAR, END_YEAR + 1):
        p = DATA_RAW / "api" / "top" / f"{year}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        rows = d.get(str(year), []) if isinstance(d, dict) else []
        for r in rows[:top_n_per_year]:
            if "team_id" in r:
                ids.add(int(r["team_id"]))
    # From /results/{year}/ — every team that placed in any event
    for year in range(START_YEAR, END_YEAR + 1):
        p = DATA_RAW / "api" / "results" / f"{year}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        if not isinstance(d, dict):
            continue
        for ev in d.values():
            for s in ev.get("scores", []):
                if "team_id" in s:
                    ids.add(int(s["team_id"]))
    # From /top-by-country/
    for p in (DATA_RAW / "api" / "top_by_country").glob("*.json"):
        d = json.loads(p.read_text())
        if isinstance(d, dict):
            for rows in d.values():
                if not isinstance(rows, list):
                    continue
                for r in rows:
                    if isinstance(r, dict) and "team_id" in r:
                        ids.add(int(r["team_id"]))
    return ids


def phase2(top_n: int = 100, min_events: int = 10, min_active_years: int = 3):
    """Phase 2: per-team detail (yearly rating panel) for the Tier-1 sampling set
    per Codex round 5. Default Tier-1 ≈ 34K teams (academic ∪ top-100/yr ∪ ≥10 events
    ∪ ≥3 active years), ~47 hr at API 5 s lane.
    """
    ids = discover_team_ids(top_n_per_year=top_n,
                             min_events=min_events,
                             min_active_years=min_active_years,
                             include_academic=True)
    eta_hr = len(ids) * 5 / 3600
    logger.info(
        f"Phase 2 Tier-1 sample: {len(ids):,} teams "
        f"(academic ∪ top-{top_n}/yr ∪ ≥{min_events}ev ∪ ≥{min_active_years}yr); "
        f"ETA ~{eta_hr:.1f} hr at 5 s/req"
    )
    client = PoliteClient()
    try:
        new = 0
        for i, tid in enumerate(sorted(ids), 1):
            if collect_team(client, tid):
                new += 1
            if i % 100 == 0:
                logger.info(f"  progress: {i}/{len(ids)} ({new} new)")
        logger.info(f"Phase 2 complete — {new} new team files.")
    finally:
        client.close()


# ------------------------------------------------------------------ Summary ---

def summary():
    rows = []
    for sub in ("events", "results", "top", "top_by_country", "votes", "teams"):
        d = DATA_RAW / "api" / sub
        if not d.exists():
            rows.append((sub, 0, 0))
            continue
        files = list(d.glob("*.json"))
        bytes_total = sum(f.stat().st_size for f in files)
        rows.append((sub, len(files), bytes_total))
    print(f"{'endpoint':<20} {'files':>8} {'MB':>10}")
    for sub, n, b in rows:
        print(f"{sub:<20} {n:>8} {b/1e6:>10.2f}")


# ------------------------------------------------------------------ CLI ---

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["phase1", "phase1b", "phase2", "summary"])
    ap.add_argument("--year", type=int, default=None,
                    help="(phase1) restrict to a single year for a small-scope test run")
    ap.add_argument("--skip-country", action="store_true",
                    help="(phase1) skip /top-by-country/ collection (saves ~8 min)")
    ap.add_argument("--top-n", type=int, default=100,
                    help="(phase2) include top-N teams per year (default 100)")
    ap.add_argument("--min-events", type=int, default=10,
                    help="(phase2) include teams with ≥ N events ever (default 10)")
    ap.add_argument("--min-active-years", type=int, default=3,
                    help="(phase2) include teams active in ≥ N calendar years (default 3)")
    args = ap.parse_args()
    if args.phase == "phase1":
        phase1(only_year=args.year, skip_country=args.skip_country)
    elif args.phase == "phase1b":
        phase1b()
    elif args.phase == "phase2":
        phase2(top_n=args.top_n,
               min_events=args.min_events,
               min_active_years=args.min_active_years)
    else:
        summary()


if __name__ == "__main__":
    main()
