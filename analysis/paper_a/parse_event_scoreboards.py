#!/usr/bin/env python3
"""Codex round 10 B1 — parse 2,689 event HTML files → canonical scoreboard CSV.

Per /event/{id}/, CTFtime renders a scoreboard table with columns
  | Place | Team | Country | Points |

Some events have >1,000 rows (e.g. event 2085 = 1,207 rows). We parse every
event HTML, extract scoreboard rows + auxiliary metadata (weight from page,
tabs present, organizers), and emit:

  data/processed/paper_a/event_scoreboards.csv
      event_id, team_id, place, score, team_name, team_country, parsed_at,
      parser_confidence, source_file

  data/processed/paper_a/event_scoreboard_audit.csv
      event_id, parsed_rows, api_participants, abs_diff, parser_status,
      n_pre_blocks, page_chars

Audit table compares parsed rows vs /api/v1/events/{id}.participants (Codex
round 10 #C bullet about pagination / hidden rows).
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from lxml import html as lh

ROOT = Path(__file__).resolve().parent.parent.parent
HTML_EV = ROOT / "data" / "raw" / "html" / "event"
EVENTS_API = ROOT / "data" / "raw" / "api" / "events"
OUT_DIR = ROOT / "data" / "processed" / "paper_a"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------- helpers

def load_api_event_participants() -> dict[int, int]:
    """{event_id: participants_count_from_api}"""
    out: dict[int, int] = {}
    for p in EVENTS_API.glob("*.json"):
        if p.name.endswith(".meta.json"):
            continue
        for e in json.loads(p.read_text()):
            try:
                eid = int(e["id"])
                out[eid] = int(e.get("participants") or 0)
            except Exception:
                continue
    return out


def parse_scoreboard(html_text: str) -> tuple[list[dict], dict]:
    """Returns (row_list, meta).
    Each row dict: place, team_id, team_name, team_country, score
    Each meta:      weight_displayed, tabs, pre_block_count, page_chars,
                    table_count, status, warnings
    """
    doc = lh.fromstring(html_text)
    warnings: list[str] = []
    # Strip chrome
    for el in list(doc.xpath('//script | //style | //nav | //header | //footer | //link | //meta | //noscript')):
        if el.getparent() is not None:
            el.getparent().remove(el)

    text = doc.text_content()
    page_chars = len(' '.join(text.split()))

    # Locate the scoreboard table — CTFtime uses class="past_event_rating" or
    # related. Rows live directly under <table> (no <tbody>/<thead>).
    candidates = (
        doc.xpath('//table[contains(@class,"past_event_rating")]')
        or doc.xpath('//table[contains(@class,"table-striped")]')
        or doc.xpath('//table[.//th[contains(text(),"Place")]]')
        or doc.xpath('//table')
    )
    rows: list[dict] = []
    used_table = None
    for tbl in candidates:
        all_tr = tbl.xpath('.//tr')
        # A scoreboard has at least 3 data rows
        data_rows = [r for r in all_tr if not r.xpath('.//th')]
        if len(data_rows) < 3:
            continue
        # Validate that this looks like a scoreboard: data rows contain a
        # /team/{id} link and a numeric place anchor somewhere
        has_team_link = any(r.xpath('.//a[contains(@href,"/team/")]') for r in data_rows[:3])
        if not has_team_link:
            continue
        used_table = tbl

        for tr in data_rows:
            tds = tr.xpath('.//td')
            if len(tds) < 3:
                continue
            # Find the place: first cell whose stripped text is an integer
            place = None
            place_idx = None
            for i, td in enumerate(tds):
                t = (td.text_content() or "").strip()
                if t.isdigit():
                    place = int(t)
                    place_idx = i
                    break
            if place is None:
                continue
            # Team cell: the cell containing /team/{id} link
            team_id = None
            team_name = ""
            team_cell_idx = None
            for i, td in enumerate(tds):
                link = (td.xpath('.//a[contains(@href,"/team/")]/@href') or [""])[0]
                m_tm = re.search(r"/team/(\d+)", link)
                if m_tm:
                    team_id = int(m_tm.group(1))
                    team_name = (td.xpath('.//a[contains(@href,"/team/")]/text()') or [""])[0].strip()
                    team_cell_idx = i
                    break
            # Country: img alt; usually 2-letter (KR, US) OR src filename hint
            country = ""
            for img in tr.xpath('.//img'):
                alt = (img.get("alt") or "").strip()
                src = img.get("src") or ""
                if alt and len(alt) <= 3 and re.fullmatch(r"[A-Za-z]+", alt):
                    country = alt.upper(); break
                m_src = re.search(r"/sf/([a-z]{2,3})\.svg", src)
                if m_src:
                    country = m_src.group(1).upper(); break
            # Score: numeric cells AFTER the team cell; take the first one
            score = ""
            after = team_cell_idx + 1 if team_cell_idx is not None else place_idx + 1
            for td in tds[after:]:
                t = (td.text_content() or "").strip()
                if re.fullmatch(r"[\d.,]+", t):
                    score = t.replace(",", "")
                    break
            rows.append({
                "place": place,
                "team_id": team_id,
                "team_name": team_name,
                "team_country": country,
                "score": score,
            })
        break  # use the first valid table

    meta = {
        "page_chars": page_chars,
        "table_count": len(doc.xpath('//table')),
        "pre_block_count": len(doc.xpath('//pre')),
        "used_table_class": (used_table.get('class') if used_table is not None else ""),
    }
    # Weight from page (displayed)
    m_w = re.search(r"Rating weight:\s*([\d.]+)", text)
    if m_w:
        meta["weight_displayed"] = float(m_w.group(1))
    return rows, meta


def event_id_from_filename(path: Path) -> int | None:
    m = re.match(r"(\d+)\.html", path.name)
    return int(m.group(1)) if m else None


def main():
    files = sorted(HTML_EV.glob("*.html"))
    print(f"event HTML files: {len(files):,}")
    api_participants = load_api_event_participants()
    print(f"API events lookup: {len(api_participants):,}")

    scores_out = OUT_DIR / "event_scoreboards.csv"
    audit_out = OUT_DIR / "event_scoreboard_audit.csv"

    with scores_out.open("w", newline="", encoding="utf-8") as fs, \
         audit_out.open("w", newline="", encoding="utf-8") as fa:
        ws = csv.writer(fs)
        ws.writerow(["event_id", "team_id", "place", "score", "team_name",
                      "team_country", "parsed_at", "parser_confidence",
                      "source_file"])
        wa = csv.writer(fa)
        wa.writerow(["event_id", "parsed_rows", "api_participants",
                      "abs_diff_rows", "parser_status",
                      "table_count", "page_chars",
                      "weight_displayed", "used_table_class"])

        n_total = 0; n_parsed = 0; n_empty = 0; rows_total = 0
        now = datetime.now(timezone.utc).isoformat()
        for f in files:
            n_total += 1
            eid = event_id_from_filename(f)
            if eid is None:
                continue
            try:
                rows, meta = parse_scoreboard(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception as e:
                wa.writerow([eid, 0, api_participants.get(eid, ""), "",
                              f"error:{type(e).__name__}", "", "", "", ""])
                continue
            n_parsed += 1
            api_p = api_participants.get(eid)
            if not rows:
                n_empty += 1
                status = "empty_scoreboard"
            elif api_p and len(rows) < api_p * 0.95:  # only flag undercounts
                status = "row_count_undercount"
            else:
                status = "ok"

            for r in rows:
                ws.writerow([eid, r.get("team_id") or "", r["place"],
                              r["score"], r["team_name"], r["team_country"],
                              now, status, f.name])
                rows_total += 1
            wa.writerow([eid, len(rows), api_p if api_p is not None else "",
                          abs(len(rows) - api_p) if api_p else "",
                          status, meta["table_count"], meta["page_chars"],
                          meta.get("weight_displayed", ""),
                          meta.get("used_table_class", "")])
            if n_total % 200 == 0:
                print(f"  [{n_total}/{len(files)}] parsed_ok={n_parsed} empty={n_empty} total_rows={rows_total:,}")

    print(f"\nDONE")
    print(f"  files: {n_total:,}; parsed_ok: {n_parsed:,}; empty: {n_empty:,}")
    print(f"  total scoreboard rows: {rows_total:,}")
    print(f"  → {scores_out}")
    print(f"  → {audit_out}")


if __name__ == "__main__":
    main()
