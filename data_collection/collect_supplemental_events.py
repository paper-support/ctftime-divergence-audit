#!/usr/bin/env python3
"""Phase 1c — supplemental fetch for events present in /results/ but missing
from /events/ monthly-window collection. ~105 events at last count.

Runs on the API lane (5 s, file-lock-shared). Only intended to be run AFTER
Phase 2 finishes, to avoid slowing the per-team detail crawl.

Output: data/raw/api/events_supplemental/{event_id}.json + .meta.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils import (
    PoliteClient,
    DATA_RAW,
    already_have,
    atomic_write_json,
    setup_logging,
)

API_ROOT = "https://ctftime.org/api/v1"
OUT_DIR = DATA_RAW / "api" / "events_supplemental"
logger = setup_logging("collect_supplemental_events")


def discover_missing_event_ids() -> set[int]:
    events_set: set[int] = set()
    for p in (DATA_RAW / "api" / "events").glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        for e in json.loads(p.read_text()):
            if "id" in e:
                events_set.add(int(e["id"]))
    results_set: set[int] = set()
    for p in (DATA_RAW / "api" / "results").glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        d = json.loads(p.read_text())
        if isinstance(d, dict):
            results_set.update(int(k) for k in d.keys())
    # also include anything already supplemental-fetched as "have"
    have = {int(p.stem) for p in OUT_DIR.glob("*.json") if p.stem.isdigit()}
    return (results_set - events_set) - have


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="cap how many supplemental events to fetch this run")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    todo = sorted(discover_missing_event_ids())
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        logger.info("nothing to do; all results-side events have metadata")
        return
    logger.info(f"supplemental events to fetch: {len(todo):,}; ETA "
                f"{len(todo)*5/60:.1f} min on API lane (5 s)")

    client = PoliteClient()
    try:
        new = 0
        for i, eid in enumerate(todo, 1):
            url = f"{API_ROOT}/events/{eid}/"
            out = OUT_DIR / f"{eid}.json"
            if already_have(out):
                continue
            try:
                d = client.get_json(url)
            except Exception as e:
                logger.warning(f"event {eid}: {e}")
                continue
            if atomic_write_json(out, d, url):
                new += 1
            if i % 25 == 0:
                logger.info(f"  progress: {i}/{len(todo)} ({new} new)")
        logger.info(f"DONE — {new} new events.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
