#!/usr/bin/env python3
"""T1 part 3 — Build vintage-aligned cross-sectional panel for RQ-A1.

Per Codex Round 12: 'vintage-aligned cross-sectional + divergence residual design'.

For each GCI/NCSI vintage, define a CTF observation window:
  GCI 2017  ↔ CTF window 2016–2018
  GCI 2020  ↔ CTF window 2019–2021
  GCI 2024  ↔ CTF window 2023–2025
  NCSI 2026 ↔ CTF window 2024–2026

For each country in each window, compute CTF performance metrics, then join
with the index percentile and the WB controls. Output is the analysis-ready
table for RQ-A1 regression / divergence audits.

Outputs:
  data/processed/paper_a/rq_a1_vintage_panel.csv
    iso2, iso3, vintage_year, source, ctf_window_start, ctf_window_end,
    index_percentile, index_score_raw, index_scale,
    ctf_top10_count, ctf_top50_count, ctf_top100_count,
    ctf_n_teams, ctf_n_events, ctf_median_place,
    ctf_top10_percentile, ctf_top50_percentile, ctf_active_team_percentile,
    divergence_score (= ctf_active_team_percentile − index_percentile),
    wb_gdp_per_capita_ppp, wb_internet_users_pct, wb_population, wb_tertiary_education_pct,
    is_sovereign_like
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data" / "processed" / "paper_a"

WINDOWS = [
    ("GCI", 2017, 2016, 2018),
    ("GCI", 2020, 2019, 2021),
    ("GCI", 2024, 2023, 2025),
    ("NCSI", 2026, 2024, 2026),
]


def percentile_rank(values: list[float], higher_is_better: bool = True) -> list[float]:
    n = len(values)
    if n <= 1:
        return [100.0] * n
    indexed = sorted(enumerate(values), key=lambda x: x[1], reverse=higher_is_better)
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
    # ---- Load canonical mapping (iso2 → iso3, name)
    canonical = {}
    with (PA / "countries_canonical.csv").open() as f:
        for r in csv.DictReader(f):
            canonical[r["iso2"]] = {
                "iso3": r["iso3"],
                "name": r["canonical_name"],
                "is_sovereign_like": int(r["is_sovereign_like"]),
            }

    # ---- Load CTF country×year panel
    ctf_panel = []
    with (PA / "country_year_panel_v2.csv").open() as f:
        for r in csv.DictReader(f):
            ctf_panel.append({
                "iso2": r["country"],
                "year": int(r["year"]),
                "n_teams": int(r["n_teams"]),
                "n_events": int(r["n_events"]),
                "n_academic_teams": int(r["n_academic_teams"]),
                "top10_appearances": int(r["top10_appearances"]),
                "top50_appearances": int(r["top50_appearances"]),
                "top100_appearances": int(r["top100_appearances"]),
                "median_place": float(r["median_place"]) if r["median_place"] else None,
                "total_appearances": int(r["total_appearances"]),
            })

    # ---- Load external indices long table
    indices = []
    with (PA / "external_indices_long.csv").open() as f:
        for r in csv.DictReader(f):
            indices.append(r)

    # ---- Load World Bank (real values, time-varying)
    # Use the latest available value per country per indicator (forward-filled)
    wb = {}
    with (PA / "worldbank_latest_per_country.csv").open() as f:
        for r in csv.DictReader(f):
            wb[r["iso2"]] = {
                "gdp_per_capita_ppp": r.get("gdp_per_capita_ppp", ""),
                "internet_users_pct": r.get("internet_users_pct", ""),
                "population": r.get("population", ""),
                "tertiary_education_pct": r.get("tertiary_education_pct", ""),
            }

    # ---- For each window, aggregate CTF metrics over the window years
    out_rows = []
    for source, vintage, win_start, win_end in WINDOWS:
        # subset of indices for this vintage
        vintage_indices = {
            r["iso2"]: r for r in indices
            if r["source"] == source and int(r["vintage_year"]) == vintage
        }

        # aggregate CTF over window
        ctf_window = defaultdict(lambda: {
            "n_teams_max": 0, "n_events_sum": 0, "n_academic_teams_max": 0,
            "top10_sum": 0, "top50_sum": 0, "top100_sum": 0,
            "place_list": [], "total_appearances_sum": 0, "years_active": 0,
        })
        for r in ctf_panel:
            if win_start <= r["year"] <= win_end:
                w = ctf_window[r["iso2"]]
                w["n_teams_max"] = max(w["n_teams_max"], r["n_teams"])
                w["n_events_sum"] += r["n_events"]
                w["n_academic_teams_max"] = max(w["n_academic_teams_max"], r["n_academic_teams"])
                w["top10_sum"] += r["top10_appearances"]
                w["top50_sum"] += r["top50_appearances"]
                w["top100_sum"] += r["top100_appearances"]
                if r["median_place"] is not None:
                    w["place_list"].append(r["median_place"])
                w["total_appearances_sum"] += r["total_appearances"]
                w["years_active"] += 1

        # compute within-vintage percentile for CTF active-team count (key A1 metric)
        ctf_isos = list(ctf_window.keys())
        active_counts = [ctf_window[i]["n_teams_max"] for i in ctf_isos]
        top10_counts = [ctf_window[i]["top10_sum"] for i in ctf_isos]
        top50_counts = [ctf_window[i]["top50_sum"] for i in ctf_isos]

        active_pct = percentile_rank(active_counts)
        top10_pct = percentile_rank(top10_counts)
        top50_pct = percentile_rank(top50_counts)

        pct_lookup = {
            iso: {"active": ap, "top10": t10p, "top50": t50p}
            for iso, ap, t10p, t50p in zip(ctf_isos, active_pct, top10_pct, top50_pct)
        }

        # join with index
        union = set(vintage_indices.keys()) | set(ctf_window.keys())
        for iso2 in sorted(union):
            idx = vintage_indices.get(iso2)
            ctf = ctf_window.get(iso2)
            can = canonical.get(iso2, {})
            wb_row = wb.get(iso2, {})

            index_pct = float(idx["percentile_rank"]) if idx else None
            active_pct_v = pct_lookup.get(iso2, {}).get("active")

            row = {
                "iso2": iso2,
                "iso3": can.get("iso3", ""),
                "canonical_name": can.get("name", ""),
                "is_sovereign_like": can.get("is_sovereign_like", 1),
                "source": source,
                "vintage_year": vintage,
                "ctf_window_start": win_start,
                "ctf_window_end": win_end,
                # index
                "index_score_raw": idx["score_raw"] if idx else "",
                "index_scale": idx["scale_note"] if idx else "",
                "index_rank": idx["rank_in_vintage"] if idx else "",
                "index_n_in_vintage": idx["n_in_vintage"] if idx else "",
                "index_percentile": index_pct if index_pct is not None else "",
                # CTF window aggregates
                "ctf_n_teams_max": ctf["n_teams_max"] if ctf else "",
                "ctf_n_events_sum": ctf["n_events_sum"] if ctf else "",
                "ctf_n_academic_teams_max": ctf["n_academic_teams_max"] if ctf else "",
                "ctf_top10_sum": ctf["top10_sum"] if ctf else "",
                "ctf_top50_sum": ctf["top50_sum"] if ctf else "",
                "ctf_top100_sum": ctf["top100_sum"] if ctf else "",
                "ctf_total_appearances_sum": ctf["total_appearances_sum"] if ctf else "",
                "ctf_median_place_avg": round(sum(ctf["place_list"]) / len(ctf["place_list"]), 1) if ctf and ctf["place_list"] else "",
                "ctf_years_active_in_window": ctf["years_active"] if ctf else 0,
                # within-vintage CTF percentile
                "ctf_active_team_percentile": active_pct_v if active_pct_v is not None else "",
                "ctf_top10_percentile": pct_lookup.get(iso2, {}).get("top10", ""),
                "ctf_top50_percentile": pct_lookup.get(iso2, {}).get("top50", ""),
                # divergence = CTF pct − index pct (positive = CTF over-performs vs. index)
                "divergence_score": (
                    round(active_pct_v - index_pct, 2)
                    if active_pct_v is not None and index_pct is not None
                    else ""
                ),
                # WB controls (time-invariant in this version; will time-vary in future)
                "wb_gdp_per_capita_ppp": wb_row.get("gdp_per_capita_ppp", ""),
                "wb_internet_users_pct": wb_row.get("internet_users_pct", ""),
                "wb_population": wb_row.get("population", ""),
                "wb_tertiary_education_pct": wb_row.get("tertiary_education_pct", ""),
                # flag for analysis subsetting
                "has_index": int(idx is not None),
                "has_ctf": int(ctf is not None),
                "has_both": int(idx is not None and ctf is not None),
            }
            out_rows.append(row)

    out = PA / "rq_a1_vintage_panel.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {out} ({len(out_rows)} rows)")

    # Diagnostics
    from collections import Counter
    by_vintage = Counter(r["vintage_year"] for r in out_rows)
    has_both_by_vintage = Counter(r["vintage_year"] for r in out_rows if r["has_both"])
    print(f"\nRows per vintage / both-data:")
    for v in [2017, 2020, 2024, 2026]:
        print(f"  vintage {v}: total={by_vintage.get(v,0)}, with both index+CTF={has_both_by_vintage.get(v,0)}")

    # Top divergent countries (per vintage)
    print(f"\nTop policy-rich / CTF-poor (index pct > ctf pct, negative divergence):")
    for v in [2017, 2020, 2024]:
        rows_v = [r for r in out_rows if r["vintage_year"] == v and r["has_both"]]
        rows_v.sort(key=lambda r: float(r["divergence_score"]))
        print(f"  --- vintage {v} ---")
        for r in rows_v[:5]:
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:30]:30s}) "
                  f"idx_pct={r['index_percentile']:>5} ctf_pct={r['ctf_active_team_percentile']:>5} "
                  f"div={r['divergence_score']:>7}")

    print(f"\nTop CTF-rich / policy-light (positive divergence):")
    for v in [2017, 2020, 2024]:
        rows_v = [r for r in out_rows if r["vintage_year"] == v and r["has_both"]]
        rows_v.sort(key=lambda r: -float(r["divergence_score"]))
        print(f"  --- vintage {v} ---")
        for r in rows_v[:5]:
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:30]:30s}) "
                  f"idx_pct={r['index_percentile']:>5} ctf_pct={r['ctf_active_team_percentile']:>5} "
                  f"div={r['divergence_score']:>7}")


if __name__ == "__main__":
    main()
