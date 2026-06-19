#!/usr/bin/env python3
"""Phase 0.5 G1-G7 gate check — runs all gates that are feasible with current data.

Outputs `data/processed/validation_gates.md` and `validation_gates.csv`. Each gate
gets one of:
  PASS  — threshold met, the dependent RQ is cleared
  FAIL  — threshold missed, deviation must be logged in paper/deviations.md
  SCOPE — scope-gate failure: RQ scope downgrade, no block
  PEND  — feasible but dependent data still being collected
  SKIP  — depends on a parser/script not yet ready

Codex round-3 thresholds:
  G1 hard:   /results/{year}/ ↔ /stats/{year}/ ranking agreement ≥ 98%
  G2 hard:   event_tasks task-ID coverage vs writeup index ≥ 95%
  G3 hard:   writeup plain-text usability ≥ 80%
  G4 hard:   English-detection FP rate < 5% (manual)
  G5 scope:  tier-2 academic evidence yield ≥ 30%
  G6 hard:   country mismatch / migration ambiguity rate < 10%
  G7 scope:  historical /event/{id}/weight populated rate ≥ 60% main / 30-60 % appendix / <30 % omit
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from lxml import html as lh

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
VAL = RAW / "validation"
OUT_MD = ROOT / "data" / "processed" / "validation_gates.md"
OUT_CSV = ROOT / "data" / "processed" / "validation_gates.csv"

# ----------------------- helpers

def strip_html(html: str) -> str:
    try:
        doc = lh.fromstring(html)
        # Remove scripts, styles
        for el in doc.xpath('//script | //style | //nav | //header | //footer'):
            el.getparent().remove(el)
        # Get the main content area if possible
        main = (doc.xpath('//div[@id="content"]') or
                doc.xpath('//div[contains(@class,"content")]') or
                [doc])[0]
        return ' '.join(main.text_content().split())
    except Exception:
        return ""


# Simple English heuristic: ASCII ratio + stop-word density
EN_STOPWORDS = {"the", "and", "to", "of", "a", "in", "is", "we", "this", "that",
                "for", "with", "on", "as", "by", "it", "was", "be", "are", "from"}

def english_score(text: str) -> tuple[float, float, bool]:
    """Returns (ascii_ratio, stopword_density, is_english_likely)."""
    if not text:
        return 0.0, 0.0, False
    ascii_n = sum(1 for c in text if ord(c) < 128)
    ascii_ratio = ascii_n / len(text)
    words = re.findall(r"[A-Za-z]{2,}", text.lower())
    if not words:
        return ascii_ratio, 0.0, False
    stop_n = sum(1 for w in words if w in EN_STOPWORDS)
    stop_density = stop_n / len(words)
    is_en = ascii_ratio >= 0.85 and stop_density >= 0.05 and len(words) >= 50
    return ascii_ratio, stop_density, is_en


# ----------------------- gates

def gate_g1():
    """SKIP — /stats/{year}/ HTML parser is broken; need to fix before this gate runs."""
    return {"id": "G1", "tier": "hard",
            "name": "/results/ ↔ /stats/ annual ranking agreement",
            "status": "SKIP", "value": "—", "threshold": "≥98%",
            "note": "Awaiting /stats/{year}/ parser fix (deferred from round 7)."}


def gate_g2():
    """PEND — event_tasks data still being collected by HTML chain (currently in events stage)."""
    fetched = len(list((RAW / "html" / "event_tasks").glob("*.html")))
    return {"id": "G2", "tier": "hard",
            "name": "event_tasks task-ID coverage vs writeup index",
            "status": "PEND", "value": f"event_tasks fetched: {fetched}",
            "threshold": "≥95%",
            "note": "HTML chain still in events stage; event_tasks not yet collected."}


def gate_g3():
    """G3 — writeup usability ≥ 80%."""
    files = sorted((VAL / "writeup").glob("*.html"))
    if not files:
        return {"id": "G3", "tier": "hard", "name": "writeup plain-text usable rate",
                "status": "PEND", "value": "no validation writeups found",
                "threshold": "≥80%", "note": "Validation crawl had no writeup output."}
    total = 0; usable = 0; flagged_short = 0; flagged_nonen = 0
    samples_nonen = []
    for f in files:
        total += 1
        text = strip_html(f.read_text(encoding="utf-8", errors="ignore"))
        ar, sd, is_en = english_score(text)
        if len(text) < 200:
            flagged_short += 1
        elif not is_en:
            flagged_nonen += 1
            if len(samples_nonen) < 5:
                samples_nonen.append((f.name, ar, sd, len(text)))
        else:
            usable += 1
    rate = usable / max(1, total)
    status = "PASS" if rate >= 0.80 else "FAIL"
    return {"id": "G3", "tier": "hard", "name": "writeup plain-text usable rate",
            "status": status, "value": f"{usable}/{total} = {rate:.1%}",
            "threshold": "≥80%",
            "note": f"flagged short(<200ch): {flagged_short}; flagged non-EN: {flagged_nonen}; "
                    f"non-EN samples: {samples_nonen[:3]}"}


def gate_g4():
    """G4 — English-detection FP rate (manual audit). Emit a sample list for review."""
    return {"id": "G4", "tier": "hard",
            "name": "English-detection false-positive rate (manual)",
            "status": "PEND",
            "value": "queue 30 random writeups for manual review",
            "threshold": "<5% FP",
            "note": "Manual review queue should be added in next iteration."}


def gate_g5():
    """G5 (scope) — tier-2 academic evidence yield: from 50 academic-flagged team HTML pages,
    count how many have university/edu evidence in their content."""
    files = sorted((VAL / "team").glob("academic-*.html"))
    if not files:
        return {"id": "G5", "tier": "scope",
                "name": "tier-2 academic evidence yield",
                "status": "PEND", "value": "no academic team validation files",
                "threshold": "≥30%", "note": "Validation crawl missing academic team pages."}
    pat = re.compile(
        r"\b(university|college|institute of technology|polytechnic|"
        r"\.edu\b|\.ac\.[a-z]{2}\b|école|universidad|universität|大学|학교|"
        r"undergraduate|laboratory|computer science department|cs department|"
        r"academia|faculty)\b",
        re.I,
    )
    total = 0; yes = 0; samples_yes = []
    for f in files:
        total += 1
        text = strip_html(f.read_text(encoding="utf-8", errors="ignore"))
        if pat.search(text):
            yes += 1
            if len(samples_yes) < 3:
                samples_yes.append(f.name)
    rate = yes / max(1, total)
    status = "PASS" if rate >= 0.30 else "SCOPE-DOWNGRADE"
    return {"id": "G5", "tier": "scope",
            "name": "tier-2 academic evidence yield",
            "status": status, "value": f"{yes}/{total} = {rate:.1%}",
            "threshold": "≥30%",
            "note": f"sample yes: {samples_yes}; below threshold means tier-2/3 evidence "
                    f"NOT used as model features (per Codex round 5)."}


def gate_g6():
    """G6 — country mismatch / migration ambiguity rate.
    Compare API teams_index country to country shown on /team/{id}/ HTML page.
    Need ID extraction from validation team filename.
    """
    files = sorted((VAL / "team").glob("*.html"))
    if not files:
        return {"id": "G6", "tier": "hard",
                "name": "country mismatch / migration ambiguity rate",
                "status": "PEND", "value": "no team validation files",
                "threshold": "<10%", "note": "Validation team pages not yet collected."}
    # Build {team_id → API country}
    team_country: dict[int, str] = {}
    for p in (RAW / "api" / "teams_index").glob("*.json"):
        if p.name.endswith(".meta.json"): continue
        d = json.loads(p.read_text())
        for r in d.get("result", []):
            if isinstance(r, dict) and "id" in r:
                team_country[int(r["id"])] = (r.get("country") or "").upper()
    total = 0; mismatch = 0; ambiguous = 0; matched = 0; samples = []
    for f in files:
        m = re.search(r"-(\d+)\.html", f.name)
        if not m: continue
        tid = int(m.group(1))
        api_cc = team_country.get(tid, "")
        try:
            doc = lh.fromstring(f.read_text(encoding="utf-8", errors="ignore"))
            html_cc_alts = doc.xpath('//h2//img/@alt')
            html_cc = (html_cc_alts[0].upper() if html_cc_alts else "")
        except Exception:
            continue
        total += 1
        if not api_cc and not html_cc:
            ambiguous += 1
        elif api_cc == html_cc:
            matched += 1
        else:
            mismatch += 1
            if len(samples) < 5:
                samples.append((tid, f"api={api_cc!r}", f"html={html_cc!r}"))
    rate = mismatch / max(1, total)
    status = "PASS" if rate < 0.10 else "FAIL"
    return {"id": "G6", "tier": "hard",
            "name": "country mismatch / migration ambiguity rate",
            "status": status, "value": f"mismatch {mismatch}/{total} = {rate:.1%} "
                                       f"(ambiguous {ambiguous}, matched {matched})",
            "threshold": "<10%",
            "note": f"sample mismatches: {samples}"}


VOTE_ROWS_RE = re.compile(r"data\.addRows\(\s*\[(.*?)\]\s*\)", re.S)
VOTE_PAIR_RE = re.compile(r"\[\s*'([^']+)'\s*,\s*(\d+)\s*\]")

def parse_event_weight_votes(html_text: str) -> list[tuple[str, int]]:
    """CTFtime renders /event/{id}/weight as Google Charts JS inline.
    Vote rows live in `data.addRows([['user', weight], …])` — extract them."""
    m = VOTE_ROWS_RE.search(html_text)
    if not m: return []
    return [(u, int(w)) for u, w in VOTE_PAIR_RE.findall(m.group(1))]


def gate_g7():
    """G7 (scope) — historical /event/{id}/weight populated rate.
    Pages render votes via Google Charts JS, not HTML tables — parse JS instead.
    """
    weight_files = sorted((VAL / "event").glob("*-weight.html"))
    if not weight_files:
        return {"id": "G7", "tier": "scope",
                "name": "historical /event/{id}/weight populated rate",
                "status": "PEND", "value": "no /event/.../weight files",
                "threshold": "≥60% main / 30-60% appendix / <30% omit",
                "note": "Validation event-weight pages not collected."}
    total = 0; populated = 0; vote_counts = []; samples_empty = []
    for f in weight_files:
        m = re.match(r"(\d{4})-(\d+)-weight\.html", f.name)
        if not m: continue
        yr = int(m.group(1))
        if yr > 2020: continue
        total += 1
        try:
            votes = parse_event_weight_votes(f.read_text(encoding="utf-8", errors="ignore"))
            if votes:
                populated += 1
                vote_counts.append(len(votes))
            else:
                if len(samples_empty) < 5: samples_empty.append(f.name)
        except Exception:
            if len(samples_empty) < 5: samples_empty.append(f.name)
    if total == 0:
        return {"id": "G7", "tier": "scope",
                "name": "historical /event/{id}/weight populated rate",
                "status": "PEND",
                "value": "no 2012-2020 event-weight files in validation",
                "threshold": "≥60% main / 30-60% appendix / <30% omit",
                "note": "Validation event sample lacks 2012-2020 weight stratum."}
    rate = populated / total
    if rate >= 0.60:   status = "PASS-FULL"
    elif rate >= 0.30: status = "SCOPE-APPENDIX"
    else:              status = "SCOPE-OMIT"
    mean_votes = sum(vote_counts) / len(vote_counts) if vote_counts else 0
    return {"id": "G7", "tier": "scope",
            "name": "historical /event/{id}/weight populated rate",
            "status": status,
            "value": f"{populated}/{total} = {rate:.1%}; mean votes/populated event ≈ {mean_votes:.1f}",
            "threshold": "≥60% main / 30-60% appendix / <30% omit",
            "note": f"empty samples: {samples_empty}; "
                    f"votes parsed via JS-array regex (`data.addRows([['user',w],…])`)"}


def main():
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    gates = [gate_g1(), gate_g2(), gate_g3(), gate_g4(), gate_g5(), gate_g6(), gate_g7()]

    # CSV
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "tier", "name", "status", "value",
                                            "threshold", "note"])
        w.writeheader()
        for g in gates: w.writerow(g)

    # Markdown
    md = ["# Phase 0.5 Gate-Check Report\n",
          "Generated post Codex round 7. Source: data/raw/validation/.\n",
          "\n| ID | Tier | Status | Value | Threshold | Name |\n",
          "|---|---|---|---|---|---|\n"]
    for g in gates:
        md.append(f"| {g['id']} | {g['tier']} | **{g['status']}** | "
                  f"{g['value']} | {g['threshold']} | {g['name']} |\n")
    md.append("\n## Notes\n\n")
    for g in gates:
        md.append(f"### {g['id']} — {g['name']}\n\n{g['note']}\n\n")

    OUT_MD.write_text("".join(md), encoding="utf-8")
    print(f"WROTE {OUT_MD}")
    for g in gates:
        print(f"  {g['id']} {g['tier']:>5}  {g['status']:<15} {g['value']}")


if __name__ == "__main__":
    main()
