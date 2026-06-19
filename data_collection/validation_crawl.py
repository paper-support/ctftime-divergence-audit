#!/usr/bin/env python3
"""Phase 0.5 — small-sample validation crawl.

Per Codex round 1: before committing 1.5+ days of full crawl, we run a stratified
small sample to validate that:

  V1. country attribution is recoverable (does /team/{id}/ HTML differ from API?)
  V2. academic-flag precision (manual sanity check on ~50 academic-flagged teams)
  V3. /results/ + /stats/ HTML can reconstruct full annual rankings (no gaps?)
  V4. /event/{id}/weight history is stable for old events (or has it been wiped?)
  V5. /writeup/{id} text quality varies by era — is 2011-2014 NLP-usable?
  V6. /event/{id}/tasks/ task_id discovery covers all tasks-with-writeups

Sample plan (small, ~6 hr total at 10 s/req):
  - 6 anchor years: 2012, 2015, 2018, 2021, 2023, 2025
  - For each anchor year: pull 30 events (top 10 by participants, mid 10, low 10)
  - For each sampled event: /event/{id}/, /event/{id}/tasks/, /event/{id}/weight
  - 50 academic-flagged teams + 50 non-academic teams (random) → /team/{id}/
  - 6 anchor years × /stats/{year}/  (full annual rankings)
  - 200 writeups stratified across 6 era cohorts → /writeup/{id} for QA
  Total ≈ 6×30×3 + 100 + 6 + 200 ≈ 846 requests × 10 s ≈ 2.4 hr

Outputs land in `data/raw/validation/` separate from the main corpus.
A summary report is written to `data/processed/validation_report.md`.

Usage:
    python3 data_collection/validation_crawl.py
    python3 data_collection/validation_crawl.py --skip-stage events
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import hashlib

import httpx
from lxml import html as lxml_html

from utils import (
    CRAWL_DELAY_SECONDS,
    MAX_BACKOFF_SECONDS,
    MAX_RETRIES,
    USER_AGENT,
    _record_failure,
    _retry_after_seconds,
    _wait_per_host,
    setup_logging,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_API = PROJECT_ROOT / "data" / "raw" / "api"
VAL_DIR = PROJECT_ROOT / "data" / "raw" / "validation"
REPORT = PROJECT_ROOT / "data" / "processed" / "validation_report.md"

logger = setup_logging("validation_crawl")
HOST = "https://ctftime.org"

ANCHOR_YEARS = [2012, 2015, 2018, 2021, 2023, 2025]
EVENTS_PER_BUCKET = 10  # top, mid, low → 30 per year
ACADEMIC_TEAM_SAMPLE = 50
RANDOM_TEAM_SAMPLE = 50
WRITEUP_SAMPLE = 200

random.seed(20260510)


# ----------------------------------------------------------- HTTP

class Client:
    """HTML client using the shared cross-process rate limiter from utils."""
    def __init__(self):
        self.client = httpx.Client(
            timeout=60,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
            follow_redirects=True,
        )

    def get(self, url: str) -> httpx.Response | None:
        host = httpx.URL(url).host
        attempt = 0
        while True:
            _wait_per_host(host, CRAWL_DELAY_SECONDS, lane="html")
            try:
                r = self.client.get(url)
                if r.status_code in (404, 410):
                    logger.info(f"GET {url} -> {r.status_code}")
                    return r
                if r.status_code == 429 or r.status_code >= 500:
                    if attempt >= MAX_RETRIES:
                        _record_failure(url, f"HTTP {r.status_code} after {MAX_RETRIES} retries")
                        return None
                    attempt += 1
                    backoff = _retry_after_seconds(r.headers, default=min(30 * attempt, MAX_BACKOFF_SECONDS))
                    logger.warning(f"HTTP {r.status_code} on {url} — sleep {backoff:.0f}s ({attempt}/{MAX_RETRIES})")
                    time.sleep(backoff)
                    continue
                r.raise_for_status()
                logger.info(f"GET {url} -> {r.status_code} ({len(r.content)}B)")
                return r
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout, httpx.RemoteProtocolError, httpx.NetworkError) as e:
                if attempt >= MAX_RETRIES:
                    _record_failure(url, f"network exhausted: {type(e).__name__}: {e}")
                    return None
                attempt += 1
                backoff = min(30 * attempt, MAX_BACKOFF_SECONDS)
                logger.warning(f"network ({type(e).__name__}) on {url} — sleep {backoff:.0f}s ({attempt}/{MAX_RETRIES})")
                time.sleep(backoff)
            except httpx.HTTPStatusError as e:
                _record_failure(url, f"HTTP {e.response.status_code}")
                return None

    def close(self): self.client.close()


def _save_with_meta(out_path: Path, response: httpx.Response) -> None:
    """Write raw HTML + .meta.json sidecar (provenance trail, per DATA_STATEMENT)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not out_path.exists():
        out_path.write_text(response.text, encoding="utf-8")
    meta_path = out_path.with_suffix(out_path.suffix + ".meta.json")
    if not meta_path.exists():
        body = response.content
        meta = {
            "url": str(response.request.url),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": response.status_code,
            "byte_count": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "user_agent": USER_AGENT,
            "crawl_delay_s": CRAWL_DELAY_SECONDS,
        }
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------- Sampling

def stratified_event_ids() -> dict[int, list[int]]:
    """For each anchor year, return [top10, mid10, low10] event_ids by participants."""
    out: dict[int, list[int]] = {}
    for year in ANCHOR_YEARS:
        events: list[dict] = []
        for month in range(1, 13):
            p = RAW_API / "events" / f"{year:04d}-{month:02d}.json"
            if not p.exists():
                continue
            d = json.loads(p.read_text())
            if isinstance(d, list):
                events.extend(d)
        events = [e for e in events if isinstance(e, dict) and e.get("id")]
        events.sort(key=lambda e: e.get("participants", 0) or 0, reverse=True)
        if not events:
            continue
        n = len(events)
        top = [e["id"] for e in events[:EVENTS_PER_BUCKET]]
        mid_start = max(0, (n - EVENTS_PER_BUCKET) // 2)
        mid = [e["id"] for e in events[mid_start: mid_start + EVENTS_PER_BUCKET]]
        low = [e["id"] for e in events[-EVENTS_PER_BUCKET:]]
        out[year] = list(dict.fromkeys(top + mid + low))[:30]
        logger.info(f"validation: year {year} → {len(out[year])} events sampled")
    return out


def academic_and_random_team_ids() -> tuple[list[int], list[int]]:
    """From /api/v1/teams/ paginated registry pick 50 academic + 50 random."""
    academic: list[int] = []
    everyone: list[int] = []
    for p in (RAW_API / "teams_index").glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        d = json.loads(p.read_text())
        for r in d.get("result", []) if isinstance(d, dict) else []:
            if not isinstance(r, dict) or "id" not in r:
                continue
            tid = int(r["id"])
            everyone.append(tid)
            if r.get("academic"):
                academic.append(tid)
    random.shuffle(academic)
    random.shuffle(everyone)
    return academic[:ACADEMIC_TEAM_SAMPLE], everyone[:RANDOM_TEAM_SAMPLE]


def writeup_id_sample_from_index_html() -> list[int]:
    """Bootstrap a small writeup sample by fetching only a handful of /writeups
    listing pages until we have 200 IDs spread across years (validation only)."""
    return []  # populated by stage_writeups itself; placeholder for type clarity


# ----------------------------------------------------------- Stages

def stage_events(client: Client, event_ids: dict[int, list[int]]):
    out_dir = VAL_DIR / "event"
    out_dir.mkdir(parents=True, exist_ok=True)
    for year, ids in event_ids.items():
        for eid in ids:
            for kind, suffix in (("event", ""), ("tasks", "tasks/"), ("weight", "weight")):
                fname = f"{year}-{eid}-{kind}.html"
                target = out_dir / fname
                if target.exists():
                    continue
                url = f"{HOST}/event/{eid}/{suffix}"
                r = client.get(url)
                if r and r.status_code == 200:
                    _save_with_meta(target, r)


def stage_teams(client: Client, academic_ids: list[int], random_ids: list[int]):
    out_dir = VAL_DIR / "team"
    out_dir.mkdir(parents=True, exist_ok=True)
    for label, ids in (("academic", academic_ids), ("random", random_ids)):
        for tid in ids:
            target = out_dir / f"{label}-{tid}.html"
            if target.exists():
                continue
            r = client.get(f"{HOST}/team/{tid}/")
            if r and r.status_code == 200:
                _save_with_meta(target, r)


def stage_stats(client: Client):
    out_dir = VAL_DIR / "stats"
    out_dir.mkdir(parents=True, exist_ok=True)
    for year in ANCHOR_YEARS:
        target = out_dir / f"{year}.html"
        if target.exists():
            continue
        r = client.get(f"{HOST}/stats/{year}/")
        if r and r.status_code == 200:
            _save_with_meta(target, r)


def stage_writeups(client: Client):
    out_dir = VAL_DIR / "writeup"
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ids: list[str] = []
    page = 1
    while len(target_ids) < WRITEUP_SAMPLE and page < 50:
        r = client.get(f"{HOST}/writeups?page={page}")
        if not r or r.status_code != 200:
            break
        doc = lxml_html.fromstring(r.text)
        for tr in doc.xpath("//table//tbody/tr"):
            link = (tr.xpath('.//a[contains(@href,"/writeup/")]/@href') or [""])[0]
            wid = link.rsplit("/", 1)[-1]
            if wid.isdigit() and wid not in target_ids:
                target_ids.append(wid)
                if len(target_ids) >= WRITEUP_SAMPLE:
                    break
        page += 1
    logger.info(f"validation: {len(target_ids)} writeup IDs sampled")
    for wid in target_ids:
        target = out_dir / f"{wid}.html"
        if target.exists():
            continue
        r = client.get(f"{HOST}/writeup/{wid}")
        if r and r.status_code == 200:
            _save_with_meta(target, r)


# ----------------------------------------------------------- Report

def build_report():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for sub in ("event", "team", "stats", "writeup"):
        d = VAL_DIR / sub
        n = len(list(d.glob("*.html"))) if d.exists() else 0
        sz = sum(f.stat().st_size for f in d.glob("*.html")) if d.exists() else 0
        rows.append((sub, n, sz / 1e6))
    body = [f"# Validation Crawl Report\n",
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n",
            "## Inventory\n",
            "| stage | files | MB |", "|---|---|---|"]
    for s, n, m in rows:
        body.append(f"| {s} | {n} | {m:.2f} |")
    body += [
        "",
        "## Manual checks to perform NEXT (per Codex Round 1)",
        "- V1. Open ~10 random `team/random-*.html` and `team/academic-*.html` —",
        "  verify country and badges are present; compare with /api/v1/teams/{id}/",
        "  for the same teams. Note discrepancies.",
        "- V2. Open ~10 academic-team pages — does the team profile actually look",
        "  academic (university domain, advisor, lab page)? Estimate precision.",
        "- V3. For 1-2 anchor years, parse `event/*-event.html` scoreboards and",
        "  cross-check totals against /api/v1/results/{year}/ counts.",
        "- V4. For 1-2 events from 2012/2015, verify `event/*-weight.html` returns",
        "  vote rows (vs the API's empty historical /votes/).",
        "- V5. Sample 20 writeups across years; assess plain-text quality, length,",
        "  PII presence (handles/IPs/etc.), language detection.",
        "- V6. For 1-2 events, compare `event_tasks` page against writeup-index",
        "  task IDs — completeness check.",
        "",
        "Findings get written into PLAN.md v3 BEFORE we launch full crawl.",
    ]
    REPORT.write_text("\n".join(body) + "\n", encoding="utf-8")
    logger.info(f"report written → {REPORT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-stage", action="append", default=[],
                    choices=["events", "teams", "stats", "writeups"],
                    help="(repeatable) skip a stage")
    args = ap.parse_args()
    VAL_DIR.mkdir(parents=True, exist_ok=True)

    event_ids = stratified_event_ids() if "events" not in args.skip_stage else {}
    academic_ids, random_ids = academic_and_random_team_ids() if "teams" not in args.skip_stage else ([], [])
    logger.info(
        f"plan: events={sum(len(v) for v in event_ids.values())}, "
        f"academic_teams={len(academic_ids)}, random_teams={len(random_ids)}, "
        f"stats_years={len(ANCHOR_YEARS)}, writeups={WRITEUP_SAMPLE}"
    )
    client = Client()
    try:
        if "events" not in args.skip_stage and event_ids:
            stage_events(client, event_ids)
        if "teams" not in args.skip_stage and (academic_ids or random_ids):
            stage_teams(client, academic_ids, random_ids)
        if "stats" not in args.skip_stage:
            stage_stats(client)
        if "writeups" not in args.skip_stage:
            stage_writeups(client)
    finally:
        client.close()
        build_report()


if __name__ == "__main__":
    main()
