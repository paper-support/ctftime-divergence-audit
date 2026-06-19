#!/usr/bin/env python3
"""CTFtime writeup crawler — Paper B (NLP corpus).

Two stages, both resumable across network outages:
  Stage A — INDEX: walk /writeups?page=N → manifest.jsonl of all writeup IDs + meta.
            ~few hundred requests, ~1 hr.
  Stage B — DETAIL: for each writeup ID, fetch /writeup/{id} and save raw HTML.
            ~80–150 K requests, ~9–17 days at 10 s polite delay.

Uses httpx (no scrapling dependency). Network errors retry forever with exponential
backoff up to 10 min. Files already on disk are skipped silently — interrupt and
restart anytime.

Usage:
    python3 collect_writeups.py index
    python3 collect_writeups.py detail [--limit N]
    python3 collect_writeups.py status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from lxml import html as lxml_html

from utils import (
    CRAWL_DELAY_SECONDS,
    PoliteHTMLClient,
    USER_AGENT,
    setup_logging,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW = PROJECT_ROOT / "data" / "raw" / "writeups"
INDEX_DIR = RAW / "index"
DETAIL_DIR = RAW / "detail"
INDEX_DIR.mkdir(parents=True, exist_ok=True)
DETAIL_DIR.mkdir(parents=True, exist_ok=True)

logger = setup_logging("collect_writeups")
HOST = "https://ctftime.org"


# --------------------------------------------------------------------- HTTP

Client = PoliteHTMLClient  # cross-process rate limiter from utils


# --------------------------------------------------------------------- Stage A

def stage_index():
    """Walk /writeups?page=N → manifest.jsonl. Each row:
       {writeup_id, team, team_id, event, event_id, task, task_id, page, indexed_at}
    """
    manifest_path = INDEX_DIR / "manifest.jsonl"
    seen: set[str] = set()
    last_page_seen = 0
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            try:
                rec = json.loads(line)
                seen.add(rec["writeup_id"])
                last_page_seen = max(last_page_seen, rec.get("page", 0))
            except Exception:
                pass
    logger.info(f"index resume — {len(seen)} known writeups, last page seen = {last_page_seen}")

    new_count = 0
    client = Client()
    page = max(1, last_page_seen)  # resume from last page (overwrites are de-duped by writeup_id)
    empty_streak = 0
    try:
        with manifest_path.open("a", encoding="utf-8") as mf:
            while True:
                r = client.get(f"{HOST}/writeups?page={page}")
                if r is None or r.status_code != 200:
                    logger.warning(f"page {page} failed; advancing")
                    page += 1
                    continue
                page_path = INDEX_DIR / f"page-{page:04d}.html"
                if not page_path.exists():
                    page_path.write_text(r.text, encoding="utf-8")

                doc = lxml_html.fromstring(r.text)
                rows = doc.xpath("//table[contains(@class,'table')]//tbody/tr")
                added = 0
                for tr in rows:
                    tds = tr.xpath(".//td")
                    if len(tds) < 4:
                        continue
                    wlink = (tds[-1].xpath(".//a/@href") or [""])[0]
                    wid = wlink.rsplit("/", 1)[-1]
                    if not wid or wid in seen:
                        continue
                    seen.add(wid)
                    rec = {
                        "writeup_id": wid,
                        "team": (tds[0].xpath(".//a/text()") or [""])[0].strip(),
                        "team_id": ((tds[0].xpath(".//a/@href") or [""])[0]).rsplit("/", 1)[-1],
                        "event": (tds[1].xpath(".//a/text()") or [""])[0].strip(),
                        "event_id": ((tds[1].xpath(".//a/@href") or [""])[0]).rsplit("/", 1)[-1],
                        "task": (tds[2].xpath(".//a/text()") or [""])[0].strip(),
                        "task_id": ((tds[2].xpath(".//a/@href") or [""])[0]).rsplit("/", 1)[-1],
                        "page": page,
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    mf.flush()
                    added += 1
                    new_count += 1

                logger.info(f"page {page}: {len(rows)} rows, {added} new (total seen {len(seen)})")
                if len(rows) == 0:
                    empty_streak += 1
                    if empty_streak >= 3:
                        logger.info("3 empty pages — assuming end of index")
                        break
                else:
                    empty_streak = 0
                page += 1
    finally:
        client.close()
    logger.info(f"index DONE — {new_count} new manifest rows; total {len(seen)}.")


# --------------------------------------------------------------------- Stage B

def stage_detail(limit: int | None = None):
    manifest_path = INDEX_DIR / "manifest.jsonl"
    if not manifest_path.exists():
        sys.exit("manifest.jsonl missing — run `index` stage first")

    todo: list[dict] = []
    for line in manifest_path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        wid = rec.get("writeup_id", "")
        if not wid or not wid.isdigit():
            continue
        if (DETAIL_DIR / f"{wid}.html").exists():
            continue
        todo.append(rec)

    if limit:
        todo = todo[:limit]
    logger.info(f"detail: {len(todo)} writeups queued")
    if not todo:
        return

    client = Client()
    try:
        for i, rec in enumerate(todo, 1):
            wid = rec["writeup_id"]
            r = client.get(f"{HOST}/writeup/{wid}")
            if r is None or r.status_code != 200:
                logger.warning(f"writeup {wid}: HTTP {r.status_code if r else 'None'} — skip")
                continue
            html_path = DETAIL_DIR / f"{wid}.html"
            html_path.write_text(r.text, encoding="utf-8")
            doc = lxml_html.fromstring(r.text)
            meta = {
                **rec,
                "url": str(r.request.url),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "status": r.status_code,
                "byte_count": len(r.content),
                "title": (doc.xpath("//h2/text()") or [""])[0].strip(),
                "tags": [a.text_content().strip()
                         for a in doc.xpath("//a[contains(@href,'/task/tags/')]")],
                "rating_text": next(iter(doc.xpath("//*[contains(text(),'Rating')]/text()")), ""),
            }
            html_path.with_suffix(".html.meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if i % 25 == 0 or i == len(todo):
                logger.info(f"detail progress {i}/{len(todo)} (last wid {wid})")
    finally:
        client.close()
    logger.info(f"detail DONE — {len(todo)} attempted.")


# --------------------------------------------------------------------- Status

def status():
    n_pages = len(list(INDEX_DIR.glob("page-*.html")))
    manifest = INDEX_DIR / "manifest.jsonl"
    n_manifest = sum(1 for _ in manifest.open()) if manifest.exists() else 0
    n_html = len(list(DETAIL_DIR.glob("*.html")))
    n_meta = len(list(DETAIL_DIR.glob("*.html.meta.json")))
    print(f"index pages         : {n_pages}")
    print(f"manifest rows       : {n_manifest}")
    print(f"detail HTML files   : {n_html}")
    print(f"detail meta files   : {n_meta}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["index", "detail", "status"])
    ap.add_argument("--limit", type=int, default=None,
                    help="(detail) cap number of new writeups to fetch this run")
    args = ap.parse_args()
    {"index": stage_index, "detail": lambda: stage_detail(args.limit), "status": status}[args.stage]()


if __name__ == "__main__":
    main()
