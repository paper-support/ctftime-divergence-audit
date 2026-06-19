#!/usr/bin/env python3
"""HTML-only data — endpoints not exposed by the CTFtime API.

Targets:
  - /event/{id}/        full scoreboard (API top is capped at 100) + tasks list per event
  - /task/{id}          challenge description, official category, points, writeup count
  - /team/{id}/         per-event participation history, badges, members (when public)
  - /lastlog?page=N     platform-event stream (publish/scoreboard/delete)
  - /stats/{year}/{cc}/ historical country×year team rankings

All requests respect 10 s crawl-delay (robots.txt). Raw HTML preserved + parsed JSON
sidecar with extracted structured fields. Resumable.

Usage:
    python3 collect_html.py events                  # /event/{id}/ for every API event
    python3 collect_html.py tasks                   # /task/{id} for every task discovered
    python3 collect_html.py teams [--top-n 500]     # /team/{id}/ for filtered subset
    python3 collect_html.py lastlog [--max-pages N] # /lastlog walk
    python3 collect_html.py stats                   # /stats/{year}/{cc}/ panel
    python3 collect_html.py status
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from lxml import html as lxml_html

from utils import (
    CRAWL_DELAY_SECONDS,
    DATA_RAW,
    PoliteHTMLClient,
    USER_AGENT,
    setup_logging,
    write_html_with_meta,
)

logger = setup_logging("collect_html")

HOST = "https://ctftime.org"
HTML_RAW = DATA_RAW / "html"
for sub in ("event", "event_tasks", "event_weight", "task", "team", "lastlog",
            "stats", "stats_year", "methodology"):
    (HTML_RAW / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- HTTP client

# Shared cross-process rate limiter from utils.PoliteHTMLClient.
HTMLClient = PoliteHTMLClient


def write_html(out_path: Path, response: httpx.Response, parsed: dict) -> None:
    """Save raw HTML + JSON sidecar via the shared utility (provenance + extracted)."""
    write_html_with_meta(out_path, response, extracted=parsed)


def parse(response: httpx.Response):
    return lxml_html.fromstring(response.text)


# ---------------------------------------------------------------- Discovery

def all_event_ids() -> set[int]:
    """All event IDs that appear in any /api/v1/events/ monthly file."""
    ids: set[int] = set()
    for p in (DATA_RAW / "api" / "events").glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        try:
            for ev in json.loads(p.read_text()):
                if isinstance(ev, dict) and "id" in ev:
                    ids.add(int(ev["id"]))
        except Exception:
            continue
    return ids


def all_team_ids_topN(top_n: int = 500) -> set[int]:
    """Team IDs appearing in /top/{year}/ rows (capped 100/year on server) + /results
    top top_n placements per event."""
    ids: set[int] = set()
    for p in (DATA_RAW / "api" / "top").glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        d = json.loads(p.read_text())
        for rows in d.values():
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict) and "team_id" in r:
                        ids.add(int(r["team_id"]))
    for p in (DATA_RAW / "api" / "results").glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        d = json.loads(p.read_text())
        if not isinstance(d, dict):
            continue
        for ev in d.values():
            for s in ev.get("scores", [])[:top_n]:
                if "team_id" in s:
                    ids.add(int(s["team_id"]))
    return ids


# ---------------------------------------------------------------- Per-page extractors

def extract_event_page(doc) -> dict:
    """From /event/{id}/ — title, scoreboard size, weight, organizer, tasks list, voting."""
    out = {}
    out["title"] = (doc.xpath("//h2/text()") or [""])[0].strip()
    # Tabs typically: Overview / Tasks and writeups / Vote / Scoreboard
    tabs = [a.text_content().strip() for a in doc.xpath("//ul[contains(@class,'nav-tabs')]//a")]
    out["tabs"] = tabs
    # Try to find the displayed weight, participants
    txt = doc.text_content()
    m = re.search(r"Rating weight:\s*([\d.]+)", txt)
    if m: out["weight_displayed"] = float(m.group(1))
    m = re.search(r"Event organizers", txt)
    if m:
        org_links = doc.xpath("//a[contains(@href,'/team/')]/text()")
        out["organizers_displayed"] = [o.strip() for o in org_links[:10]]
    # Scoreboard table rows
    sb_rows = doc.xpath("//table[contains(@class,'table-striped')]//tr")
    out["scoreboard_row_count"] = max(0, len(sb_rows) - 1)
    return out


def extract_task_page(doc) -> dict:
    """From /task/{id} — name, points, tags, parent event, writeup count."""
    out = {}
    out["title"] = (doc.xpath("//h2/text()") or [""])[0].strip()
    txt = doc.text_content()
    m = re.search(r"Points?:\s*(\d+)", txt)
    if m: out["points"] = int(m.group(1))
    m = re.search(r"Tags?:\s*([^\n]+)", txt)
    if m: out["tags"] = [t.strip() for t in m.group(1).split(",") if t.strip()]
    out["event_links"] = doc.xpath("//a[contains(@href,'/event/')]/@href")
    writeup_rows = doc.xpath("//table//tr/td/a[contains(@href,'/writeup/')]/@href")
    out["writeup_links"] = list(dict.fromkeys(writeup_rows))  # dedup, preserve order
    out["writeup_count"] = len(out["writeup_links"])
    return out


def extract_team_page(doc) -> dict:
    """From /team/{id}/ — country, primary_alias, badges, recent events table."""
    out = {}
    out["name"] = (doc.xpath("//h2/text()") or [""])[0].strip()
    flag = doc.xpath("//h2//img/@alt")
    if flag: out["country"] = flag[0].strip()
    # Year tabs (rating)
    out["year_tabs"] = doc.xpath("//ul[contains(@class,'nav-tabs')]//a/text()")
    # Recent events count
    out["events_table_row_count"] = len(doc.xpath("//table[contains(@class,'table-striped')]//tr")) - 1
    return out


def extract_lastlog_page(doc) -> dict:
    """From /lastlog?page=N — list of {datetime, event_id, change_text}."""
    rows = []
    for li in doc.xpath("//div[contains(@class,'span9')]//div[contains(@class,'lastlog')]//tr") \
              or doc.xpath("//table//tr"):
        tds = li.xpath(".//td")
        if len(tds) < 2:
            continue
        ts = tds[0].text_content().strip()
        link = tds[1].xpath(".//a/@href")
        text = tds[1].text_content().strip()
        rows.append({"timestamp_text": ts, "event_link": link[0] if link else "", "text": text})
    return {"row_count": len(rows), "rows": rows[:200]}


def extract_stats_page(doc) -> dict:
    """From /stats/{year}/{cc}/ — table of rank|team|country|rating points."""
    rows = []
    for tr in doc.xpath("//table[contains(@class,'table')]//tbody/tr"):
        cells = [c.text_content().strip() for c in tr.xpath(".//td")]
        link = tr.xpath(".//a[contains(@href,'/team/')]/@href")
        rows.append({"cells": cells, "team_link": link[0] if link else ""})
    return {"row_count": len(rows), "rows": rows}


def extract_event_tasks_page(doc) -> dict:
    """From /event/{id}/tasks/ — flat list of tasks for that event.

    Each <tr> has the task name as a link plus a writeup-count link to the same
    /task/{id} URL. Dedup by href.
    """
    seen: dict[str, dict] = {}
    for a in doc.xpath('//table//tr/td/a[contains(@href,"/task/")]'):
        href = a.get("href", "")
        text = (a.text_content() or "").strip()
        if href not in seen:
            seen[href] = {"task_link": href, "task_id": href.rsplit("/", 1)[-1],
                          "name": text, "writeup_count_text": ""}
        else:
            # second occurrence: usually the writeup count number
            if text.isdigit():
                seen[href]["writeup_count_text"] = text
    rows = list(seen.values())
    return {"task_count": len(rows), "tasks": rows}


def extract_event_weight_page(doc) -> dict:
    """From /event/{id}/weight — vote breakdown (per-team weight contributions)."""
    txt = doc.text_content()
    out: dict = {}
    m = re.search(r"Rating weight:\s*([\d.]+)", txt)
    if m:
        out["weight"] = float(m.group(1))
    rows = []
    for tr in doc.xpath('//table//tbody/tr'):
        cells = [c.text_content().strip() for c in tr.xpath('.//td')]
        if cells:
            rows.append(cells)
    out["vote_rows"] = rows
    out["vote_row_count"] = len(rows)
    return out


def extract_stats_year_page(doc) -> dict:
    """From /stats/{year}/ (no country) — full annual ranking. Bypasses the
    /api/v1/top/{year}/ 100-cap."""
    rows = []
    for tr in doc.xpath('//table[contains(@class,"table")]//tbody/tr'):
        cells = [c.text_content().strip() for c in tr.xpath('.//td')]
        team_link = tr.xpath('.//a[contains(@href,"/team/")]/@href')
        country_img = tr.xpath('.//img/@alt')
        rows.append({
            "cells": cells,
            "team_link": team_link[0] if team_link else "",
            "country": country_img[0] if country_img else "",
        })
    return {"row_count": len(rows), "rows": rows[:1500]}  # cap stored rows


def extract_methodology_page(doc) -> dict:
    """For one-shot pages: title + plain text body."""
    title = (doc.xpath('//h1/text()') or doc.xpath('//h2/text()') or [""])[0].strip()
    body = doc.text_content().strip()
    return {"title": title, "char_count": len(body)}


# ---------------------------------------------------------------- Collectors

def collect_events(client: HTMLClient, limit: int | None = None):
    ids = sorted(all_event_ids())
    if limit:
        ids = ids[:limit]
    logger.info(f"events: {len(ids)} pages to fetch (skipping any already on disk)")
    for i, eid in enumerate(ids, 1):
        out = HTML_RAW / "event" / f"{eid}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}/event/{eid}/")
        if r and r.status_code == 200:
            write_html(out, r, extract_event_page(parse(r)))
        if i % 25 == 0:
            logger.info(f"events progress {i}/{len(ids)}")


def collect_tasks(client: HTMLClient, task_ids: list[int] | None = None,
                  source_dir: Path | None = None):
    """If task_ids not provided, derive them from event-page extraction sidecars."""
    if task_ids is None:
        task_ids = sorted(_discover_task_ids())
    logger.info(f"tasks: {len(task_ids)} pages to fetch")
    for i, tid in enumerate(task_ids, 1):
        out = HTML_RAW / "task" / f"{tid}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}/task/{tid}")
        if r and r.status_code == 200:
            write_html(out, r, extract_task_page(parse(r)))
        if i % 25 == 0:
            logger.info(f"tasks progress {i}/{len(task_ids)}")


def _discover_task_ids() -> set[int]:
    """Walk event pages' parsed sidecars to find task links of form /task/N."""
    ids: set[int] = set()
    for meta in (HTML_RAW / "event").glob("*.html.meta.json"):
        try:
            d = json.loads(meta.read_text())
            for href in d.get("extracted", {}).get("tabs", []):
                pass  # tabs is just labels; we'll walk task ids via writeup index later
        except Exception:
            continue
    # fallback: derive task ids from API events (some have task_count, but no IDs)
    return ids


def collect_teams(client: HTMLClient, top_n: int = 500):
    ids = sorted(all_team_ids_topN(top_n))
    logger.info(f"teams: {len(ids)} pages to fetch")
    for i, tid in enumerate(ids, 1):
        out = HTML_RAW / "team" / f"{tid}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}/team/{tid}/")
        if r and r.status_code == 200:
            write_html(out, r, extract_team_page(parse(r)))
        if i % 25 == 0:
            logger.info(f"teams progress {i}/{len(ids)}")


def collect_lastlog(client: HTMLClient, max_pages: int = 50):
    for page in range(1, max_pages + 1):
        out = HTML_RAW / "lastlog" / f"page-{page:04d}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}/lastlog?page={page}")
        if not (r and r.status_code == 200):
            break
        parsed = extract_lastlog_page(parse(r))
        if parsed["row_count"] == 0:
            logger.info(f"lastlog page {page} empty — stopping")
            break
        write_html(out, r, parsed)


def collect_event_tasks(client: HTMLClient, limit: int | None = None):
    """For each known event_id, fetch /event/{id}/tasks/ — the canonical place to
    discover task IDs."""
    ids = sorted(all_event_ids())
    if limit:
        ids = ids[:limit]
    logger.info(f"event_tasks: {len(ids)} pages to fetch")
    for i, eid in enumerate(ids, 1):
        out = HTML_RAW / "event_tasks" / f"{eid}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}/event/{eid}/tasks/")
        if r and r.status_code == 200:
            write_html(out, r, extract_event_tasks_page(parse(r)))
        if i % 25 == 0:
            logger.info(f"event_tasks progress {i}/{len(ids)}")


def collect_event_weight(client: HTMLClient, limit: int | None = None):
    """For each event, fetch /event/{id}/weight — voting breakdown."""
    ids = sorted(all_event_ids())
    if limit:
        ids = ids[:limit]
    logger.info(f"event_weight: {len(ids)} pages to fetch")
    for i, eid in enumerate(ids, 1):
        out = HTML_RAW / "event_weight" / f"{eid}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}/event/{eid}/weight")
        if r and r.status_code == 200:
            write_html(out, r, extract_event_weight_page(parse(r)))
        if i % 25 == 0:
            logger.info(f"event_weight progress {i}/{len(ids)}")


def collect_stats_year(client: HTMLClient, years=range(2011, 2027)):
    """Full annual ranking via /stats/{year}/ — bypasses API top/{year}/ 100-cap."""
    for year in years:
        out = HTML_RAW / "stats_year" / f"{year}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}/stats/{year}/")
        if r and r.status_code == 200:
            write_html(out, r, extract_stats_year_page(parse(r)))


def collect_methodology(client: HTMLClient):
    """One-shot pages: rating formula, about, FAQ — for the methodology section."""
    pages = {
        "rating-formula": "/rating-formula/",
        "about": "/about/",
        "faq": "/faq/",
    }
    for name, path in pages.items():
        out = HTML_RAW / "methodology" / f"{name}.html"
        if out.exists() and out.with_suffix(".html.meta.json").exists():
            continue
        r = client.get(f"{HOST}{path}")
        if r and r.status_code == 200:
            write_html(out, r, extract_methodology_page(parse(r)))


def collect_stats(client: HTMLClient, years=range(2011, 2027), countries: list[str] | None = None):
    countries = countries or [
        "us", "ru", "cn", "kr", "de", "fr", "gb", "jp", "in", "br",
        "pl", "ua", "tw", "vn", "il", "se", "fi", "no", "dk", "nl",
        "be", "es", "it", "tr", "ca", "au", "sg", "hk", "ch", "at",
    ]
    for year in years:
        for cc in countries:
            out = HTML_RAW / "stats" / f"{year}-{cc}.html"
            if out.exists() and out.with_suffix(".html.meta.json").exists():
                continue
            r = client.get(f"{HOST}/stats/{year}/{cc}/")
            if r and r.status_code == 200:
                write_html(out, r, extract_stats_page(parse(r)))


# ---------------------------------------------------------------- Status

def _discover_task_ids() -> set[int]:
    """Walk event_tasks sidecars to extract task IDs."""
    ids: set[int] = set()
    for meta in (HTML_RAW / "event_tasks").glob("*.html.meta.json"):
        try:
            d = json.loads(meta.read_text())
            for t in d.get("extracted", {}).get("tasks", []):
                tid = t.get("task_id", "")
                if tid.isdigit():
                    ids.add(int(tid))
        except Exception:
            continue
    return ids


def status():
    rows = []
    for sub in ("event", "event_tasks", "event_weight", "task", "team",
                "lastlog", "stats", "stats_year", "methodology"):
        d = HTML_RAW / sub
        n = len(list(d.glob("*.html"))) if d.exists() else 0
        m = len(list(d.glob("*.html.meta.json"))) if d.exists() else 0
        b = sum(f.stat().st_size for f in d.glob("*.html")) if d.exists() else 0
        rows.append((sub, n, m, b))
    print(f"{'kind':<10} {'html':>8} {'meta':>8} {'MB':>10}")
    for sub, n, m, b in rows:
        print(f"{sub:<10} {n:>8} {m:>8} {b/1e6:>10.2f}")


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=[
        "events", "event_tasks", "event_weight", "tasks", "teams",
        "lastlog", "stats", "stats_year", "methodology", "status"
    ])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--top-n", type=int, default=500, help="(teams) keep top-N per year")
    ap.add_argument("--max-pages", type=int, default=50, help="(lastlog) max page count")
    args = ap.parse_args()

    if args.kind == "status":
        status(); return
    client = HTMLClient()
    try:
        if args.kind == "events":         collect_events(client, args.limit)
        elif args.kind == "event_tasks":  collect_event_tasks(client, args.limit)
        elif args.kind == "event_weight": collect_event_weight(client, args.limit)
        elif args.kind == "tasks":        collect_tasks(client)
        elif args.kind == "teams":        collect_teams(client, args.top_n)
        elif args.kind == "lastlog":      collect_lastlog(client, args.max_pages)
        elif args.kind == "stats":        collect_stats(client)
        elif args.kind == "stats_year":   collect_stats_year(client)
        elif args.kind == "methodology":  collect_methodology(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
