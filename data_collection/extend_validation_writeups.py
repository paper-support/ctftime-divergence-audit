#!/usr/bin/env python3
"""Phase 0.5 extension — fetch year-stratified pilot writeups.

Validation crawl pulled the 200 newest writeups (IDs 40569-40773), all post-2022.
For Codex round 8 pilot we need ≥30 writeups per year cohort:
  pre-2020 / 2020-2022 / post-2022.

Strategy: writeup_id ≈ submission time (monotone). We sample at strategic ID
intervals to fill the older cohorts. ID→year mapping is approximate; we resolve
year via the parent event link inside each writeup HTML.

Sample plan: 90 additional writeups → ~15 min on HTML lane (10 s).
  cohort_a (pre-2020):     IDs 100, 500, 1500, 3000, 6000, ...   → 30 IDs
  cohort_b (2020-2022):    IDs 12000, 14000, 16000, ...           → 30 IDs
  cohort_c extra post-2022: not needed (validation already 200)   → 30 IDs from gap
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils import (
    PoliteHTMLClient,
    USER_AGENT,
    setup_logging,
    write_html_with_meta,
)

logger = setup_logging("extend_validation_writeups")
HOST = "https://ctftime.org"
OUT = Path("data/raw/validation/writeup")  # same dir as validation crawl
OUT.mkdir(parents=True, exist_ok=True)


def sample_ids() -> list[int]:
    """Hand-picked IDs spanning the writeup-id timeline.
    The pre-2020 / 2020-2022 / post-2022 cohorts are loose proxies based on
    monotone-increment heuristic (verified later via event link)."""
    cohort_a = [100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000, 3500,
                4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500, 8000, 8500,
                9000, 9500, 10000, 10500, 11000, 11500, 12000, 12500, 13000, 13500]
    cohort_b = [14000, 14500, 15000, 15500, 16000, 16500, 17000, 17500, 18000, 18500,
                19000, 19500, 20000, 20500, 21000, 21500, 22000, 22500, 23000, 23500,
                24000, 24500, 25000, 25500, 26000, 26500, 27000, 27500, 28000, 28500]
    cohort_c = [29000, 29500, 30000, 30500, 31000, 31500, 32000, 32500, 33000, 33500,
                34000, 34500, 35000, 35500, 36000, 36500, 37000, 37500, 38000, 38500,
                39000, 39500, 40000, 40100, 40200, 40300, 40400, 40500, 40550, 40560]
    return cohort_a + cohort_b + cohort_c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    todo = sample_ids()
    if args.limit:
        todo = todo[:args.limit]
    todo = [w for w in todo if not (OUT / f"{w}.html").exists()]
    logger.info(f"extension fetch — {len(todo)} new writeups (~{len(todo)*10/60:.0f} min)")

    client = PoliteHTMLClient(logger_name="extend_writeup")
    try:
        ok = 0
        gone = 0
        for i, wid in enumerate(todo, 1):
            r = client.get(f"{HOST}/writeup/{wid}")
            if r is None:
                continue
            if r.status_code == 200:
                write_html_with_meta(OUT / f"{wid}.html", r)
                ok += 1
            elif r.status_code in (404, 410):
                gone += 1
            if i % 20 == 0:
                logger.info(f"  progress {i}/{len(todo)}")
    finally:
        client.close()
    logger.info(f"DONE — {ok} new writeups stored, {gone} 404/410.")


if __name__ == "__main__":
    main()
