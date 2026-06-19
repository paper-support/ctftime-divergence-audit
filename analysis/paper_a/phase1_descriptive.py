#!/usr/bin/env python3
"""Phase 1 descriptive analyses (items 1–11 from Codex round 6).

Reads only API outputs already on disk (no network). Produces:
  data/processed/paper_a/
    audit_endpoint_reconciliation.csv     ← item 1
    cohort_activity_ccdf.csv              ← item 2
    country_tag_selection.csv             ← item 3
    country_year_panel.csv                ← item 4
    worldbank_country_coverage.csv        ← item 5
    academic_base_rates_year.csv          ← item 6
    matching_feasibility_a2.csv           ← item 7
    team_year_exposure_features.csv       ← item 8
    event_ecosystem_evolution.csv         ← item 9
    event_ai_mentions.csv                 ← item 10
    csrankings_country_coverage.csv       ← item 11
    phase1_descriptive_report.md          ← combined summary

Stdlib + lxml only — no pandas required.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "paper_a"
OUT.mkdir(parents=True, exist_ok=True)

YEAR_RANGE = list(range(2011, 2027))


def write_csv(path: Path, header: list[str], rows: list[list]):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# ---------- Phase-1 raw loaders ----------

def load_events() -> list[dict]:
    events = []
    for p in sorted((RAW / "api" / "events").glob("*.json")):
        if p.name.endswith(".meta.json"):
            continue
        events.extend(json.loads(p.read_text()))
    return events


def load_results() -> dict[int, list[dict]]:
    """Returns {year: [(event_id, scores_list), ...]} flattened to per-event."""
    out: dict[int, list[tuple[int, list[dict]]]] = {}
    for p in sorted((RAW / "api" / "results").glob("*.json")):
        if p.name.endswith(".meta.json"):
            continue
        yr = int(p.stem)
        d = json.loads(p.read_text())
        if isinstance(d, dict):
            out[yr] = [(int(eid), ev.get("scores", [])) for eid, ev in d.items()]
    return out


def load_teams_index() -> list[dict]:
    teams = []
    for p in sorted((RAW / "api" / "teams_index").glob("*.json")):
        if p.name.endswith(".meta.json"):
            continue
        d = json.loads(p.read_text())
        teams.extend(d.get("result", []))
    return teams


def load_top_yearly() -> dict[str, list[dict]]:
    out = {}
    for p in sorted((RAW / "api" / "top").glob("*.json")):
        if p.name.endswith(".meta.json"):
            continue
        d = json.loads(p.read_text())
        for yr, rows in d.items():
            if isinstance(rows, list):
                out[yr] = rows
    return out


def load_worldbank() -> dict[str, dict]:
    """Returns {indicator_name: {(country_iso3, year): value, ...}}."""
    indicators: dict[str, dict] = {}
    for p in sorted((RAW / "external" / "worldbank").glob("*.json")):
        if p.name.endswith(".meta.json"):
            continue
        name = p.stem
        d = json.loads(p.read_text())
        if not (isinstance(d, list) and len(d) >= 2 and isinstance(d[1], list)):
            continue
        kv = {}
        for row in d[1]:
            try:
                cc = row.get("country", {}).get("id") or row.get("countryiso3code")
                yr = int(row.get("date"))
                v = row.get("value")
                if cc and v is not None:
                    kv[(cc, yr)] = v
            except Exception:
                continue
        indicators[name] = kv
    return indicators


def load_csrankings() -> list[dict]:
    p = RAW / "external" / "csrankings" / "csrankings.csv"
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(row)
    return out


# ---------- Item 1: endpoint reconciliation audit ----------

def item1_endpoint_audit(events, results, teams_index):
    event_ids_in_events = {int(e["id"]) for e in events if "id" in e}
    event_ids_in_results = set()
    score_rows = 0
    for yr, ev_list in results.items():
        for eid, scores in ev_list:
            event_ids_in_results.add(eid)
            score_rows += len(scores)

    registry_ids = {int(r["id"]) for r in teams_index if "id" in r}
    placed_ids = set()
    for yr, ev_list in results.items():
        for _, scores in ev_list:
            for s in scores:
                if "team_id" in s:
                    placed_ids.add(int(s["team_id"]))

    in_results_not_in_events = event_ids_in_results - event_ids_in_events
    in_events_not_in_results = event_ids_in_events - event_ids_in_results
    placed_missing_registry = placed_ids - registry_ids

    rows = [
        ["events table — unique IDs", len(event_ids_in_events)],
        ["results table — unique event IDs", len(event_ids_in_results)],
        ["events ∩ results", len(event_ids_in_events & event_ids_in_results)],
        ["events only", len(in_events_not_in_results)],
        ["results only", len(in_results_not_in_events)],
        ["score rows total", score_rows],
        ["registry teams", len(registry_ids)],
        ["distinct placed teams (any event)", len(placed_ids)],
        ["placed teams ∩ registry", len(placed_ids & registry_ids)],
        ["placed teams MISSING from registry", len(placed_missing_registry)],
        ["registry coverage of placed",
         f"{len(placed_ids & registry_ids) / max(1, len(placed_ids)):.4%}"],
        ["registry teams placed in ≥1 event",
         f"{len(placed_ids & registry_ids):,} ({len(placed_ids & registry_ids) / max(1, len(registry_ids)):.2%})"],
    ]
    write_csv(OUT / "audit_endpoint_reconciliation.csv",
              ["metric", "value"], rows)
    sanity_pass = len(placed_missing_registry) / max(1, len(placed_ids)) < 0.02
    return rows, sanity_pass, len(placed_missing_registry)


# ---------- Item 2: cohort/activity CCDF ----------

def item2_activity_ccdf(results):
    team_events: Counter = Counter()
    team_years: dict[int, set] = defaultdict(set)
    team_first_yr: dict[int, int] = {}
    team_last_yr: dict[int, int] = {}
    for yr, ev_list in results.items():
        for _, scores in ev_list:
            for s in scores:
                tid = s.get("team_id")
                if tid:
                    team_events[tid] += 1
                    team_years[tid].add(yr)
                    if tid not in team_first_yr or yr < team_first_yr[tid]:
                        team_first_yr[tid] = yr
                    if tid not in team_last_yr or yr > team_last_yr[tid]:
                        team_last_yr[tid] = yr
    rows = []
    distrib = Counter(team_events.values())
    cum = 0
    total = sum(distrib.values())
    for k in sorted(distrib):
        cum += distrib[k]
        rows.append([k, distrib[k], total - cum + distrib[k],
                     (total - cum + distrib[k]) / total])
    write_csv(OUT / "cohort_activity_ccdf.csv",
              ["events_per_team", "n_teams", "ccdf_count", "ccdf_frac"], rows)
    return team_events, team_years, team_first_yr, team_last_yr


# ---------- Item 3: country-tag selection ----------

def item3_country_tag_selection(teams_index, team_events, team_years,
                                 team_first_yr, top_team_set):
    """Compare tagged vs untagged on activity, top-100 presence, academic, first year."""
    rows = []
    for label, predicate in [
        ("country_tagged", lambda t: bool(t.get("country"))),
        ("untagged", lambda t: not t.get("country")),
    ]:
        bucket_ids = {int(t["id"]) for t in teams_index
                       if predicate(t) and "id" in t}
        n = len(bucket_ids)
        n_placed = len(bucket_ids & team_events.keys())
        events_total = sum(team_events.get(tid, 0) for tid in bucket_ids)
        years_total = sum(len(team_years.get(tid, set())) for tid in bucket_ids)
        n_top100 = len(bucket_ids & top_team_set)
        n_academic = sum(
            1 for t in teams_index
            if t.get("academic") and predicate(t) and t.get("id") in bucket_ids
        )
        rows.append([
            label, n, n_placed,
            f"{n_placed / max(1, n):.2%}",
            f"{events_total / max(1, n):.2f}",
            f"{years_total / max(1, n):.2f}",
            n_top100, f"{n_top100 / max(1, n):.4%}",
            n_academic, f"{n_academic / max(1, n):.2%}",
        ])
    write_csv(OUT / "country_tag_selection.csv",
              ["bucket", "n_teams", "n_placed", "placed_frac",
               "mean_events_per_team", "mean_active_years",
               "n_in_any_top100_year", "top100_frac",
               "n_academic", "academic_frac"], rows)
    return rows


# ---------- Item 4: country-year participation panel ----------

def item4_country_year_panel(events, results, teams_index, top_yearly):
    team_country = {int(t["id"]): t.get("country") for t in teams_index if "id" in t}
    rows = []
    # year × country table: number of distinct active teams
    panel: dict[tuple[str, int], dict] = defaultdict(lambda: {
        "active_teams": set(), "new_teams": set(), "top100_teams": set()
    })
    seen_global: set[int] = set()
    for yr in sorted(results):
        seen_this_year: set[int] = set()
        for _, scores in results[yr]:
            for s in scores:
                tid = s.get("team_id")
                if not tid: continue
                cc = team_country.get(tid)
                if cc:
                    panel[(cc, yr)]["active_teams"].add(tid)
                    seen_this_year.add(tid)
                    if tid not in seen_global:
                        panel[(cc, yr)]["new_teams"].add(tid)
        seen_global |= seen_this_year
    for yr_str, top_rows in top_yearly.items():
        try: yr = int(yr_str)
        except ValueError: continue
        for r in top_rows:
            tid = r.get("team_id")
            cc = team_country.get(tid)
            if cc:
                panel[(cc, yr)]["top100_teams"].add(tid)
    out_rows = []
    for (cc, yr), v in sorted(panel.items()):
        out_rows.append([cc, yr,
                          len(v["active_teams"]),
                          len(v["new_teams"]),
                          len(v["top100_teams"])])
    write_csv(OUT / "country_year_panel.csv",
              ["country", "year", "active_teams", "new_teams_first_seen",
               "top100_teams"], out_rows)
    return out_rows


# ---------- Item 5: World Bank coverage ----------

def item5_wb_coverage(wb, country_year_panel_rows):
    countries_in_panel = sorted({r[0] for r in country_year_panel_rows})
    rows = []
    for cc2 in countries_in_panel:
        # World Bank uses ISO3; we have ISO2 in CTFtime. Heuristic skip — record both.
        cov = {}
        for ind, kv in wb.items():
            yrs_covered = sum(
                1 for (c, y) in kv if (c == cc2.upper() or len(c) == 3) and 2011 <= y <= 2026
            )
            cov[ind] = yrs_covered
        rows.append([cc2] + [cov.get(ind, 0) for ind in sorted(wb)])
    write_csv(OUT / "worldbank_country_coverage.csv",
              ["country_iso2"] + sorted(wb), rows)
    # NB: ISO2-vs-ISO3 alignment is a known gap; flagged as a TODO.
    return rows


# ---------- Item 6: academic base rates by year ----------

def item6_academic_by_year(teams_index, team_first_yr):
    academic_set = {int(t["id"]) for t in teams_index if t.get("academic") and "id" in t}
    rows = []
    for yr in YEAR_RANGE:
        new_in_yr = {tid for tid, y in team_first_yr.items() if y == yr}
        n_total = len(new_in_yr)
        n_acad = len(new_in_yr & academic_set)
        rows.append([yr, n_total, n_acad,
                      f"{n_acad / max(1, n_total):.4%}"])
    write_csv(OUT / "academic_base_rates_year.csv",
              ["entry_year", "new_teams", "academic_new", "academic_frac"], rows)
    return rows


# ---------- Item 7: matching feasibility for A2 ----------

def item7_matching_feasibility(teams_index, team_events, team_years, team_first_yr):
    academic_set = {int(t["id"]) for t in teams_index if t.get("academic") and "id" in t}
    team_country = {int(t["id"]): t.get("country") for t in teams_index if "id" in t}

    def stratum(tid):
        events = team_events.get(tid, 0)
        years = len(team_years.get(tid, set()))
        first_yr = team_first_yr.get(tid, 9999)
        cohort = (
            "early" if first_yr <= 2015
            else "mid" if first_yr <= 2020
            else "recent"
        )
        activity = (
            "elite" if events >= 50
            else "high" if events >= 10
            else "mid" if events >= 3
            else "low"
        )
        country_known = "tagged" if team_country.get(tid) else "untagged"
        return (cohort, activity, country_known)

    aca_strata: Counter = Counter()
    non_strata: Counter = Counter()
    for tid in team_events:
        s = stratum(tid)
        if tid in academic_set: aca_strata[s] += 1
        else: non_strata[s] += 1
    keys = sorted(set(aca_strata) | set(non_strata))
    rows = []
    for k in keys:
        a, n = aca_strata.get(k, 0), non_strata.get(k, 0)
        ratio = n / max(1, a)
        common_support = "yes" if a >= 5 and n >= 5 else "no"
        rows.append([*k, a, n, f"{ratio:.1f}", common_support])
    write_csv(OUT / "matching_feasibility_a2.csv",
              ["cohort", "activity", "country_known",
               "n_academic", "n_non_academic", "non_per_aca", "common_support"],
              rows)
    return rows


# ---------- Item 8: team-year exposure features (for A3 prep) ----------

def item8_exposure_features(events, results, teams_index):
    event_meta = {int(e["id"]): e for e in events if "id" in e}
    team_country = {int(t["id"]): t.get("country") for t in teams_index if "id" in t}

    team_year: dict[tuple[int, int], dict] = defaultdict(lambda: {
        "events": 0, "weights": [], "formats": set(), "organizers": set(),
        "field_sizes": [],
    })
    for yr, ev_list in results.items():
        for eid, scores in ev_list:
            ev = event_meta.get(eid, {})
            weight = ev.get("weight") or 0.0
            fmt = ev.get("format") or "unknown"
            organizers = tuple(o.get("id") for o in (ev.get("organizers") or [])
                                if o.get("id"))
            field = len(scores)
            for s in scores:
                tid = s.get("team_id")
                if not tid: continue
                key = (int(tid), yr)
                team_year[key]["events"] += 1
                team_year[key]["weights"].append(weight)
                team_year[key]["formats"].add(fmt)
                team_year[key]["organizers"].update(organizers)
                team_year[key]["field_sizes"].append(field)
    rows = []
    for (tid, yr), v in team_year.items():
        n = v["events"]
        rows.append([tid, yr, n,
                     sum(v["weights"]) / max(1, n),
                     max(v["weights"]) if v["weights"] else 0,
                     len(v["formats"]),
                     len(v["organizers"]),
                     sum(v["field_sizes"]) / max(1, n),
                     team_country.get(tid) or ""])
    write_csv(OUT / "team_year_exposure_features.csv",
              ["team_id", "year", "events_entered", "mean_weight", "max_weight",
               "format_diversity", "organizer_diversity", "mean_field_size",
               "country"], rows)
    return rows


# ---------- Item 9: event ecosystem evolution ----------

def item9_event_evolution(events):
    by_yr: dict[int, dict] = defaultdict(lambda: {
        "events": 0, "weights": [], "participants": [], "formats": Counter(),
        "onsite": 0, "online": 0,
    })
    for ev in events:
        try:
            yr = int(ev.get("start", "0000")[:4])
        except Exception:
            continue
        if not (2011 <= yr <= 2026): continue
        b = by_yr[yr]
        b["events"] += 1
        if ev.get("weight") is not None: b["weights"].append(ev["weight"])
        if ev.get("participants") is not None: b["participants"].append(ev["participants"])
        b["formats"][ev.get("format") or "unknown"] += 1
        if ev.get("onsite"): b["onsite"] += 1
        else: b["online"] += 1
    rows = []
    all_formats = sorted({f for b in by_yr.values() for f in b["formats"]})
    for yr in sorted(by_yr):
        b = by_yr[yr]
        ws, ps = b["weights"], b["participants"]
        rows.append([
            yr, b["events"],
            f"{sum(ws) / max(1, len(ws)):.2f}",
            f"{max(ws) if ws else 0:.2f}",
            f"{sum(ps) / max(1, len(ps)):.1f}",
            f"{max(ps) if ps else 0}",
            b["onsite"], b["online"],
            *[b["formats"].get(f, 0) for f in all_formats],
        ])
    write_csv(OUT / "event_ecosystem_evolution.csv",
              ["year", "events", "mean_weight", "max_weight",
               "mean_participants", "max_participants",
               "onsite_count", "online_count",
               *[f"format_{f}" for f in all_formats]], rows)
    return rows


# ---------- Item 10: AI/LLM mentions in event descriptions (B context) ----------

def item10_ai_mentions(events):
    pat = re.compile(
        r"\b(chatgpt|gpt-?\d|llm|copilot|claude|prompt[\s-]injection|"
        r"ai-assist|machine[\s-]learning|generative[\s-]ai)\b",
        re.I,
    )
    rows = []
    by_year_count = Counter()
    by_year_total = Counter()
    for ev in events:
        try:
            yr = int(ev.get("start", "0000")[:4])
        except Exception:
            continue
        if not (2011 <= yr <= 2026): continue
        by_year_total[yr] += 1
        text = " ".join([
            ev.get("title") or "",
            ev.get("description") or "",
            ev.get("prizes") or "",
        ])
        if pat.search(text):
            by_year_count[yr] += 1
    for yr in sorted(by_year_total):
        rows.append([yr, by_year_total[yr], by_year_count[yr],
                     f"{by_year_count[yr] / max(1, by_year_total[yr]):.4%}"])
    write_csv(OUT / "event_ai_mentions.csv",
              ["year", "events", "events_with_ai_mention", "frac"], rows)
    return rows


# ---------- Item 11: CSRankings country-level coverage ----------

def item11_csrankings_coverage(csrankings_rows):
    cnt = Counter()
    for r in csrankings_rows:
        # csrankings.csv columns: name, affiliation, homepage, scholarid
        # We need an institution → country mapping which the raw file doesn't carry.
        # Record the affiliations only — country join requires a separate file.
        aff = r.get("affiliation") or ""
        cnt[aff] += 1
    top = cnt.most_common(50)
    rows = [[aff, n] for aff, n in top]
    write_csv(OUT / "csrankings_country_coverage.csv",
              ["affiliation_or_institution", "faculty_count"], rows)
    return rows


# ---------- Combined markdown report ----------

def write_report(item1_rows, sanity_pass, missing_registry,
                 item2_distrib_top, item3_rows, item4_rows,
                 item6_rows, item7_rows, item9_rows, item10_rows):
    body = []
    body.append("# Phase 1 Descriptive Report\n")
    body.append("Generated: $(date)\n")
    body.append(f"Source: Phase 1 API outputs only (events, results, top, "
                f"teams_index, votes). Phase 2 / HTML / writeups not used.\n")
    body.append("Per Codex round 6 prioritized items 1-11. Item 12 list lives "
                "in `paper/avoid_for_now.md`.\n")
    body.append("---\n")

    body.append("## Item 1 — Endpoint reconciliation audit\n")
    body.append("| metric | value |\n|---|---|\n")
    for k, v in item1_rows:
        body.append(f"| {k} | {v} |\n")
    body.append(f"\n**Sanity check (>98 % registry coverage of placed teams):** "
                f"**{'PASS' if sanity_pass else 'FAIL'}** "
                f"(missing registry: {missing_registry:,})\n\n---\n")

    body.append("## Item 2 — Activity-tail CCDF (top of distribution)\n")
    body.append("| events_per_team | n_teams | ccdf_count | ccdf_frac |\n|---|---|---|---|\n")
    for r in item2_distrib_top[:15]:
        body.append("| " + " | ".join(str(x) for x in r) + " |\n")
    body.append(f"\nFull table at `data/processed/paper_a/cohort_activity_ccdf.csv`.\n\n---\n")

    body.append("## Item 3 — Country-tag selection diagnostic\n")
    body.append("| bucket | n_teams | n_placed | placed_frac | "
                "mean_events | mean_years | n_top100 | top100_frac | "
                "n_academic | academic_frac |\n")
    body.append("|" + "|".join(["---"] * 10) + "|\n")
    for r in item3_rows:
        body.append("| " + " | ".join(str(x) for x in r) + " |\n")
    body.append("\n---\n")

    body.append("## Item 4 — Country-year participation panel (top 20 by total active)\n")
    by_country = defaultdict(int)
    for r in item4_rows:
        by_country[r[0]] += r[2]
    top_cc = sorted(by_country.items(), key=lambda x: -x[1])[:20]
    body.append("| country | total active-team-years (sum) |\n|---|---|\n")
    for cc, n in top_cc:
        body.append(f"| {cc} | {n:,} |\n")
    body.append(f"\nFull panel at `data/processed/paper_a/country_year_panel.csv`.\n\n---\n")

    body.append("## Item 6 — Academic base rate by entry year\n")
    body.append("| entry_year | new_teams | academic_new | academic_frac |\n|---|---|---|---|\n")
    for r in item6_rows:
        body.append("| " + " | ".join(str(x) for x in r) + " |\n")
    body.append("\n---\n")

    body.append("## Item 7 — Matching feasibility for A2\n")
    body.append("| cohort | activity | country | n_academic | n_non_academic | "
                "non_per_aca | common_support |\n")
    body.append("|" + "|".join(["---"] * 7) + "|\n")
    for r in item7_rows:
        body.append("| " + " | ".join(str(x) for x in r) + " |\n")
    body.append("\n---\n")

    body.append("## Item 9 — Event ecosystem evolution (year totals)\n")
    body.append("| year | events | mean_w | max_w | mean_part | max_part | onsite | online |\n")
    body.append("|" + "|".join(["---"] * 8) + "|\n")
    for r in item9_rows:
        body.append("| " + " | ".join(str(x) for x in r[:8]) + " |\n")
    body.append("\n---\n")

    body.append("## Item 10 — AI/LLM mentions in event descriptions (Paper B context)\n")
    body.append("| year | events | with_ai_mention | frac |\n|---|---|---|---|\n")
    for r in item10_rows:
        body.append("| " + " | ".join(str(x) for x in r) + " |\n")
    body.append("\n*Reminder (Codex round 6 item 10):* If AI mentions appear in "
                "event metadata pre-2022 or are too sparse, do NOT use event "
                "descriptions for B2 — fall back to writeups only.\n")
    body.append("\n---\n")

    body.append("## Items 5, 8, 11 — see CSV outputs\n")
    body.append("- `worldbank_country_coverage.csv` (item 5)\n")
    body.append("- `team_year_exposure_features.csv` (item 8 — large file, "
                "use for A3 model design)\n")
    body.append("- `csrankings_country_coverage.csv` (item 11)\n")

    (OUT / "phase1_descriptive_report.md").write_text("".join(body), encoding="utf-8")


# ---------- main ----------

def main():
    print("[load] events..."); events = load_events()
    print(f"  {len(events):,} events")
    print("[load] results...")
    results = load_results()
    print(f"  {sum(len(v) for v in results.values()):,} (year, event) pairs")
    print("[load] teams_index...")
    teams_index = load_teams_index()
    print(f"  {len(teams_index):,} teams")
    print("[load] top yearly...")
    top_yearly = load_top_yearly()
    print("[load] world bank...")
    wb = load_worldbank()
    print(f"  {len(wb)} indicators, {sum(len(v) for v in wb.values()):,} datapoints")
    print("[load] csrankings...")
    csrk = load_csrankings()
    print(f"  {len(csrk):,} faculty rows")

    print("[item 1] endpoint reconciliation...")
    item1, sanity_pass, missing = item1_endpoint_audit(events, results, teams_index)
    print(f"  sanity check: {'PASS' if sanity_pass else 'FAIL'} (missing {missing:,})")

    print("[item 2] activity CCDF...")
    team_events, team_years, team_first_yr, team_last_yr = item2_activity_ccdf(results)

    # Build set of every team that ever appeared in any year's top-100
    top_team_set = set()
    for rows in top_yearly.values():
        for r in rows:
            if isinstance(r, dict) and "team_id" in r:
                top_team_set.add(int(r["team_id"]))

    # CCDF top rows (for report)
    distrib = Counter(team_events.values())
    cum = 0
    total = sum(distrib.values())
    top_rows = []
    for k in sorted(distrib):
        cum += distrib[k]
        top_rows.append([k, distrib[k], total - cum + distrib[k],
                          f"{(total - cum + distrib[k]) / total:.4f}"])

    print("[item 3] country-tag selection...")
    item3 = item3_country_tag_selection(teams_index, team_events, team_years,
                                          team_first_yr, top_team_set)
    print("[item 4] country-year panel...")
    item4 = item4_country_year_panel(events, results, teams_index, top_yearly)
    print("[item 5] World Bank coverage...")
    item5_wb_coverage(wb, item4)
    print("[item 6] academic base rates...")
    item6 = item6_academic_by_year(teams_index, team_first_yr)
    print("[item 7] matching feasibility...")
    item7 = item7_matching_feasibility(teams_index, team_events, team_years, team_first_yr)
    print("[item 8] team-year exposure features...")
    item8_exposure_features(events, results, teams_index)
    print("[item 9] event evolution...")
    item9 = item9_event_evolution(events)
    print("[item 10] AI mentions...")
    item10 = item10_ai_mentions(events)
    print("[item 11] CSRankings coverage...")
    item11_csrankings_coverage(csrk)

    print("[report] composing markdown...")
    write_report(item1, sanity_pass, missing, top_rows, item3, item4,
                 item6, item7, item9, item10)
    print(f"DONE → {OUT}/")


if __name__ == "__main__":
    main()
