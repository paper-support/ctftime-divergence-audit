#!/usr/bin/env python3
"""Writeup INDEX crawler — Path C lynchpin.

Walks /writeups?page=N for all N. Each page has a 5-column table:
  | Event | Task | Tags | Author team | Action(link → /writeup/{id}) |

We extract each row → CSV + save raw HTML for re-extraction.
~30 rows/page × ~1,300 pages ≈ 40K writeup rows. At 10 s polite delay (HTML lane,
shared with HTML chain via file lock): ~3.6 hr alone, ~7 hr if sharing.

Output:
  data/raw/writeups/index/page-NNNN.html         (raw HTML)
  data/raw/writeups/index/page-NNNN.html.meta.json
  data/raw/writeups/index/manifest_tagged.jsonl  (one row per writeup, append)

The manifest is the file we'll feed into the tag-coverage / clustering analyses.

Resumable: skips pages already on disk. Stops after 3 consecutive empty pages.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lxml import html as lh

from utils import (
    PoliteHTMLClient,
    USER_AGENT,
    setup_logging,
    write_html_with_meta,
)

logger = setup_logging("collect_writeup_index")
HOST = "https://ctftime.org"
OUT_DIR = Path("data/raw/writeups/index")
OUT_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST = OUT_DIR / "manifest_tagged.jsonl"


def parse_index_page(html_text: str) -> list[dict]:
    """Returns a list of writeup-row dicts from one /writeups?page=N HTML."""
    doc = lh.fromstring(html_text)
    rows = []
    for tr in doc.xpath("//table//tbody/tr"):
        cells = tr.xpath(".//td")
        if len(cells) < 5:
            continue
        event_cell, task_cell, tags_cell, team_cell, action_cell = cells[:5]
        event_link = (event_cell.xpath('.//a/@href') or [""])[0]
        event_name = event_cell.text_content().strip()
        task_link = (task_cell.xpath('.//a/@href') or [""])[0]
        task_name = task_cell.text_content().strip()
        team_link = (team_cell.xpath('.//a/@href') or [""])[0]
        team_name = team_cell.text_content().strip()
        wlink = (action_cell.xpath('.//a/@href') or [""])[0]
        m_wid = re.search(r"/writeup/(\d+)", wlink)
        if not m_wid:
            continue
        # Tags cell — child elements separated by whitespace/<br>; collapse
        raw_tags = tags_cell.text_content().strip()
        tags = [t for t in re.split(r"\s+", raw_tags) if t]
        # Event ID
        m_ev = re.search(r"/event/(\d+)", event_link)
        # Task ID
        m_tk = re.search(r"/task/(\d+)", task_link)
        # Team ID
        m_tm = re.search(r"/team/(\d+)", team_link)
        rows.append({
            "writeup_id": int(m_wid.group(1)),
            "event_id": int(m_ev.group(1)) if m_ev else None,
            "event_name": event_name,
            "task_id": int(m_tk.group(1)) if m_tk else None,
            "task_name": task_name,
            "team_id": int(m_tm.group(1)) if m_tm else None,
            "team_name": team_name,
            "tags_raw": raw_tags,
            "tags": tags,
            "n_tags": len(tags),
        })
    return rows


def load_existing_writeup_ids() -> set[int]:
    """For resume: collect writeup_ids already in manifest."""
    if not MANIFEST.exists():
        return set()
    out = set()
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            out.add(int(json.loads(line)["writeup_id"]))
        except Exception:
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=2000)
    ap.add_argument("--max-empty-streak", type=int, default=3)
    args = ap.parse_args()

    seen_ids = load_existing_writeup_ids()
    logger.info(f"resume — {len(seen_ids):,} writeup_ids already in manifest")

    # Determine starting page: continue from highest page-NNNN.html on disk
    existing = sorted(int(p.stem.split("-")[1]) for p in OUT_DIR.glob("page-*.html"))
    start_page = (existing[-1] + 1) if existing else 1
    if start_page > 1:
        logger.info(f"continuing from page {start_page} (have {len(existing)} pages saved)")

    client = PoliteHTMLClient(logger_name="writeup_index")
    new_rows = 0
    empty_streak = 0
    page = start_page
    try:
        with MANIFEST.open("a", encoding="utf-8") as mf:
            while page <= args.max_pages:
                r = client.get(f"{HOST}/writeups?page={page}")
                if r is None:
                    logger.warning(f"page {page}: hard fail, stopping")
                    break
                if r.status_code in (404, 410):
                    logger.info(f"page {page}: {r.status_code} — likely end of index")
                    break
                page_path = OUT_DIR / f"page-{page:04d}.html"
                write_html_with_meta(page_path, r)

                rows = parse_index_page(r.text)
                if not rows:
                    empty_streak += 1
                    logger.info(f"page {page}: 0 rows (empty_streak={empty_streak})")
                    if empty_streak >= args.max_empty_streak:
                        logger.info(f"hit {empty_streak} consecutive empty pages — done")
                        break
                else:
                    empty_streak = 0
                    added = 0
                    for rec in rows:
                        if rec["writeup_id"] in seen_ids:
                            continue
                        seen_ids.add(rec["writeup_id"])
                        rec["indexed_at"] = datetime.now(timezone.utc).isoformat()
                        mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        added += 1
                    new_rows += added
                    mf.flush()
                    logger.info(f"page {page}: +{added}/{len(rows)} new (manifest size now {len(seen_ids):,})")
                page += 1
    finally:
        client.close()
    logger.info(f"DONE — {new_rows} new writeup rows; {len(seen_ids):,} total in manifest")


if __name__ == "__main__":
    main()
