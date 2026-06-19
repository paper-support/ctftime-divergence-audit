#!/usr/bin/env python3
"""Task (d) — Event-percentile performance divergence (per Codex Round 14).

Distinguishes 'participation' from 'performance':
  event_percentile_i = 1 - (place_i - 1) / (field_size_event - 1)
  → 1.0 = winner; 0.0 = last place

Aggregate by country × vintage window:
  median_event_percentile  — typical performance of country-tagged teams
  top10_pct_share          — fraction of appearances in top 10% of field
  top25_pct_share          — fraction in top 25%
  top50_pct_share          — fraction in top 50%

Filter to inclusion_tier='main' (≥5 teams, ≥20 events, ≥2 years active)
and produce a performance-divergence comparison alongside the activity-based one.

Output:
  data/processed/paper_a/event_percentile_country_window.csv
  data/processed/paper_a/rq_a1_vintage_panel_robust_perf.csv  (adds performance metrics)
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"

WINDOWS = [
    ("GCI", 2017, 2016, 2018),
    ("GCI", 2020, 2019, 2021),
    ("GCI", 2024, 2023, 2025),
    ("NCSI", 2026, 2024, 2026),
]


def percentile_rank(vals: list[float], higher_is_better: bool = True) -> list[float]:
    n = len(vals)
    if n <= 1:
        return [100.0] * n
    indexed = sorted(enumerate(vals), key=lambda x: x[1], reverse=higher_is_better)
    pct = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        p = (1 - (avg_rank - 1) / (n - 1)) * 100
        for k in range(i, j + 1):
            pct[indexed[k][0]] = round(p, 2)
        i = j + 1
    return pct


def main():
    # 1. Load event years
    event_year = {}
    with (PA / "events_master.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                event_year[int(r["event_id"])] = int(r["year"])
            except (ValueError, KeyError):
                pass
    print(f"Events with year: {len(event_year):,}")

    # 2. Compute field_size per event (count rows with valid place)
    field_size = defaultdict(int)
    print("Counting field sizes...")
    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            eid = int(r["event_id"]) if r.get("event_id") else None
            if eid and r.get("place"):
                field_size[eid] += 1
    print(f"Events with parsed scoreboards: {len(field_size):,}")

    # 3. Stream event_scores_enriched again, compute event_percentile per row, filter country-tagged
    # Aggregate by (country, vintage_window)
    win_lookup = {}  # year → list of (source, vintage, win_start, win_end)
    for source, vintage, ws, we in WINDOWS:
        for y in range(ws, we + 1):
            win_lookup.setdefault(y, []).append((source, vintage, ws, we))

    # country_window → {appearances: int, percentiles: [], top10_count, top25_count, top50_count}
    cw = defaultdict(lambda: {
        "appearances": 0,
        "percentiles": [],
        "top10_count": 0, "top25_count": 0, "top50_count": 0,
    })

    print("Computing event percentiles...")
    n_rows = 0
    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            country = r.get("country", "")
            place_s = r.get("place", "")
            eid_s = r.get("event_id", "")
            if not country or not place_s or not eid_s:
                continue
            eid = int(eid_s)
            place = int(place_s)
            yr = event_year.get(eid)
            if yr is None:
                continue
            fs = field_size.get(eid, 0)
            if fs <= 1 or place < 1 or place > fs:
                continue

            ep = 1.0 - (place - 1) / (fs - 1)
            n_rows += 1

            for (source, vintage, ws, we) in win_lookup.get(yr, []):
                key = (country, source, vintage)
                cw[key]["appearances"] += 1
                cw[key]["percentiles"].append(ep)
                if ep >= 0.90:
                    cw[key]["top10_count"] += 1
                if ep >= 0.75:
                    cw[key]["top25_count"] += 1
                if ep >= 0.50:
                    cw[key]["top50_count"] += 1

    print(f"Processed {n_rows:,} country-tagged team-event rows")
    print(f"Generated {len(cw):,} (country, vintage) cells with performance data")

    # 4. Compute per-country-window aggregates
    perf_rows = []
    for (country, source, vintage), d in cw.items():
        n_app = d["appearances"]
        if n_app == 0:
            continue
        median_ep = statistics.median(d["percentiles"])
        mean_ep = statistics.mean(d["percentiles"])
        perf_rows.append({
            "iso2": country,
            "source": source,
            "vintage_year": vintage,
            "perf_appearances": n_app,
            "median_event_percentile": round(median_ep, 4),
            "mean_event_percentile": round(mean_ep, 4),
            "top10_pct_share": round(d["top10_count"] / n_app, 4),
            "top25_pct_share": round(d["top25_count"] / n_app, 4),
            "top50_pct_share": round(d["top50_count"] / n_app, 4),
            "top10_pct_count": d["top10_count"],
            "top25_pct_count": d["top25_count"],
            "top50_pct_count": d["top50_count"],
        })

    out_perf = PA / "event_percentile_country_window.csv"
    with out_perf.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(perf_rows[0].keys()))
        w.writeheader()
        w.writerows(perf_rows)
    print(f"Wrote {out_perf} ({len(perf_rows)} rows)")

    # 5. Merge into existing robust panel and compute performance-based divergence
    robust = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust.csv").open()))
    perf_lookup = {(r["iso2"], r["source"], int(r["vintage_year"])): r for r in perf_rows}

    # Add performance columns
    for r in robust:
        key = (r["iso2"], r["source"], int(r["vintage_year"]))
        p = perf_lookup.get(key)
        if p:
            r["perf_appearances"] = p["perf_appearances"]
            r["median_event_percentile"] = p["median_event_percentile"]
            r["mean_event_percentile"] = p["mean_event_percentile"]
            r["top10_pct_share"] = p["top10_pct_share"]
            r["top25_pct_share"] = p["top25_pct_share"]
            r["top50_pct_share"] = p["top50_pct_share"]
        else:
            for k in ["perf_appearances", "median_event_percentile", "mean_event_percentile",
                      "top10_pct_share", "top25_pct_share", "top50_pct_share"]:
                r[k] = ""

    # 6. Within-vintage percentile of performance composite (4 metrics, equal-weight rank-avg)
    by_vintage = defaultdict(list)
    for r in robust:
        if r["inclusion_tier"] in ("main", "sensitivity") and r.get("median_event_percentile") not in ("", None):
            by_vintage[(r["source"], int(r["vintage_year"]))].append(r)

    for (source, vintage), group in by_vintage.items():
        for metric in ["median_event_percentile", "top10_pct_share",
                       "top25_pct_share", "top50_pct_share"]:
            vals = [float(r[metric]) for r in group]
            pcts = percentile_rank(vals, higher_is_better=True)
            for r, p in zip(group, pcts):
                r[f"{metric}_pct"] = p

        # Composite = equal-weight mean of 4 performance percentiles
        for r in group:
            comp = sum(r[f"{m}_pct"] for m in [
                "median_event_percentile", "top10_pct_share",
                "top25_pct_share", "top50_pct_share"
            ]) / 4
            r["performance_composite_raw"] = round(comp, 2)

        # Re-percentile the composite within vintage
        comp_vals = [r["performance_composite_raw"] for r in group]
        comp_pcts = percentile_rank(comp_vals, higher_is_better=True)
        for r, p in zip(group, comp_pcts):
            r["performance_composite_pct"] = p

    # Fill empty perf columns for non-main rows
    perf_extra = ["median_event_percentile_pct", "top10_pct_share_pct",
                  "top25_pct_share_pct", "top50_pct_share_pct",
                  "performance_composite_raw", "performance_composite_pct"]
    for r in robust:
        for k in perf_extra:
            if k not in r:
                r[k] = ""

    # 7. Performance-based divergence: performance_composite_pct - index_percentile
    for r in robust:
        try:
            perf_pct = float(r.get("performance_composite_pct", ""))
            idx_pct = float(r.get("index_percentile", ""))
            r["divergence_performance"] = round(perf_pct - idx_pct, 2)
        except (ValueError, TypeError):
            r["divergence_performance"] = ""

    # 8. Write
    out_panel = PA / "rq_a1_vintage_panel_robust_perf.csv"
    keys = list(robust[0].keys())
    with out_panel.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(robust)
    print(f"Wrote {out_panel}")

    # 9. Diagnostics: compare activity vs performance divergence
    print("\n=== Performance divergence — top NEGATIVE (high index, low performance), MAIN sample ===")
    for source, vintage in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024)]:
        eligible = [r for r in robust
                    if r["source"] == source and int(r["vintage_year"]) == vintage
                    and r["inclusion_tier"] == "main"
                    and r.get("divergence_performance") not in ("", None)]
        eligible.sort(key=lambda r: float(r["divergence_performance"]))
        print(f"\n  --- GCI {vintage} (n={len(eligible)}) ---")
        for r in eligible[:5]:
            div_a = r.get("divergence_robust", "?")
            div_p = r["divergence_performance"]
            med_ep = r.get("median_event_percentile", "?")
            top10 = r.get("top10_pct_share", "?")
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:24]:24s}) "
                  f"idx={float(r['index_percentile']):.0f} "
                  f"div_activity={float(div_a) if div_a != '' else 0:>+5.0f} "
                  f"div_perf={float(div_p):>+5.0f}  "
                  f"med_ep={med_ep}  top10share={top10}")

    print("\n=== Performance divergence — top POSITIVE (low index, high performance), MAIN sample ===")
    for source, vintage in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024)]:
        eligible = [r for r in robust
                    if r["source"] == source and int(r["vintage_year"]) == vintage
                    and r["inclusion_tier"] == "main"
                    and r.get("divergence_performance") not in ("", None)]
        eligible.sort(key=lambda r: -float(r["divergence_performance"]))
        print(f"\n  --- GCI {vintage} (n={len(eligible)}) ---")
        for r in eligible[:5]:
            div_a = r.get("divergence_robust", "?")
            div_p = r["divergence_performance"]
            med_ep = r.get("median_event_percentile", "?")
            top10 = r.get("top10_pct_share", "?")
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:24]:24s}) "
                  f"idx={float(r['index_percentile']):.0f} "
                  f"div_activity={float(div_a) if div_a != '' else 0:>+5.0f} "
                  f"div_perf={float(div_p):>+5.0f}  "
                  f"med_ep={med_ep}  top10share={top10}")


if __name__ == "__main__":
    main()
