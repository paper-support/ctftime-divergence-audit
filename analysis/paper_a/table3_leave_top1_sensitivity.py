#!/usr/bin/env python3
"""V5 P1.4 — Compute Spearman ρ after leave-top-team-out for ALL main-sample countries.

Extends the §6.6 concentration apparatus to the headline Table 3 result.
For each vintage, recompute each country's V_cv excluding its single most active
team, then re-rank within vintage and report Spearman ρ vs the index percentile.

Output:
  data/processed/paper_a/table3_leave_top1_sensitivity.csv
"""
from __future__ import annotations
import csv
import math
import random
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
BOOT_B = 2000
BOOT_SEED = 42


def percentile_rank(vals, higher_is_better=True):
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


def spearman(x, y):
    n = len(x)
    if n < 2:
        return float("nan")
    # Convert to ranks (with average ties)
    def to_ranks(vec):
        idx = sorted(range(n), key=lambda i: vec[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vec[idx[j+1]] == vec[idx[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[idx[k]] = avg
            i = j + 1
        return ranks
    rx, ry = to_ranks(x), to_ranks(y)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    denx = math.sqrt(sum((a-mx)**2 for a in rx))
    deny = math.sqrt(sum((b-my)**2 for b in ry))
    if denx == 0 or deny == 0:
        return float("nan")
    return num / (denx * deny)


def bootstrap_ci(x, y, B=2000, seed=42, alpha=0.05):
    n = len(x)
    rng = random.Random(seed)
    boots = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        bx = [x[i] for i in idx]
        by = [y[i] for i in idx]
        rho = spearman(bx, by)
        if rho == rho:  # not nan
            boots.append(rho)
    boots.sort()
    lo = boots[int(B * alpha / 2)]
    hi = boots[int(B * (1 - alpha / 2))]
    return lo, hi


def load_event_years():
    yr = {}
    with (PA / "events_master.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                yr[int(r["event_id"])] = int(r["year"])
            except (ValueError, KeyError):
                pass
    return yr


def load_field_sizes():
    fs = defaultdict(int)
    with (PA / "event_scores_enriched.csv").open() as f:
        rdr = csv.DictReader(f)
        seen = defaultdict(set)
        for r in rdr:
            try:
                eid = int(r["event_id"])
                tid = int(r["team_id"])
                seen[eid].add(tid)
            except (ValueError, KeyError):
                continue
    for eid, tset in seen.items():
        fs[eid] = len(tset)
    return fs


def load_baseline_panel():
    """For each (source, vintage): list of main-sample country rows."""
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf_region.csv").open()))
    by_vintage = defaultdict(list)
    for r in rows:
        if (r.get("inclusion_tier") == "main"
                and r.get("performance_composite_pct") not in ("", None)
                and r.get("index_percentile") not in ("", None)):
            by_vintage[(r["source"], int(r["vintage_year"]))].append(r)
    return by_vintage


def load_all_country_appearances(field_size, event_year):
    """Load (country_iso2, source, vintage) → {team_id: [(event_pct, place)]}
    for ALL countries (not just outliers). One pass over event_scores_enriched.csv."""
    appearances = defaultdict(lambda: defaultdict(list))
    with (PA / "event_scores_enriched.csv").open() as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            try:
                country = r["country"]
                if not country:
                    continue
                eid = int(r["event_id"])
                tid = int(r["team_id"])
                place = int(r["place"])
                year = event_year.get(eid)
                if year is None:
                    continue
                fs = field_size.get(eid, 0)
                if fs <= 1:
                    continue
                ep = 1 - (place - 1) / (fs - 1)
                for src, vintage, y0, y1 in WINDOWS:
                    if y0 <= year <= y1:
                        appearances[(country, src, vintage)][tid].append((ep, place))
            except (ValueError, KeyError):
                continue
    return appearances


def country_metrics(team_data):
    eps = []
    n_top10 = n_top25 = n_top50 = 0
    for entries in team_data.values():
        for ep, _ in entries:
            eps.append(ep)
            if ep >= 0.90: n_top10 += 1
            if ep >= 0.75: n_top25 += 1
            if ep >= 0.50: n_top50 += 1
    n = len(eps)
    if n == 0:
        return None
    return {
        "median": statistics.median(eps),
        "t10": n_top10 / n,
        "t25": n_top25 / n,
        "t50": n_top50 / n,
        "n": n,
    }


def main():
    print("Loading event years and field sizes...")
    event_year = load_event_years()
    field_size = load_field_sizes()
    print(f"  {len(event_year):,} events; {len(field_size):,} field-size lookups")

    print("Loading baseline main-sample panel...")
    baseline = load_baseline_panel()
    for k, v in baseline.items():
        print(f"  {k}: {len(v)} countries")

    print("Streaming ALL country appearances...")
    appearances = load_all_country_appearances(field_size, event_year)
    print(f"  {len(appearances)} (country,vintage) cells")

    out_rows = []

    for source, vintage, y0, y1 in WINDOWS:
        peers = baseline.get((source, vintage), [])
        if not peers:
            continue

        # Build per-country new V_cv after top-1 removal
        index_pct = []
        new_v_pct = []
        full_v_pct = []
        countries = []
        for prow in peers:
            iso2 = prow["iso2"]
            team_data = appearances.get((iso2, source, vintage))
            if team_data is None:
                continue

            # Identify top-1 team by appearance count
            sorted_teams = sorted(team_data.items(), key=lambda kv: -len(kv[1]))
            if not sorted_teams:
                continue
            top1_tid = sorted_teams[0][0]

            # Recompute metrics excluding top-1
            remaining = {tid: e for tid, e in team_data.items() if tid != top1_tid}
            m = country_metrics(remaining)
            if m is None or m["n"] < 5:
                # Skip if too few residual appearances
                continue

            # Build peer arrays for re-ranking
            metric_keys_panel = [
                "median_event_percentile",
                "top10_pct_share",
                "top25_pct_share",
                "top50_pct_share",
            ]
            new_vals = [m["median"], m["t10"], m["t25"], m["t50"]]

            comp_pcts = []
            for pk, nv in zip(metric_keys_panel, new_vals):
                peer_vals = [float(pp[pk]) for pp in peers if pp["iso2"] != iso2]
                combined = peer_vals + [nv]
                ranks = percentile_rank(combined, higher_is_better=True)
                comp_pcts.append(ranks[-1])
            new_composite_raw = sum(comp_pcts) / len(comp_pcts)

            peer_comps = [float(pp["performance_composite_raw"]) for pp in peers if pp["iso2"] != iso2]
            combined = peer_comps + [new_composite_raw]
            final_ranks = percentile_rank(combined, higher_is_better=True)
            new_perf_pct = final_ranks[-1]

            countries.append(iso2)
            index_pct.append(float(prow["index_percentile"]))
            new_v_pct.append(new_perf_pct)
            full_v_pct.append(float(prow["performance_composite_pct"]))

        if len(index_pct) < 5:
            continue

        # Original ρ (V_full vs I) and new ρ (V_minus_top1 vs I)
        rho_full = spearman(index_pct, full_v_pct)
        rho_new = spearman(index_pct, new_v_pct)
        ci_full = bootstrap_ci(index_pct, full_v_pct, B=BOOT_B, seed=BOOT_SEED)
        ci_new = bootstrap_ci(index_pct, new_v_pct, B=BOOT_B, seed=BOOT_SEED)

        delta_rho = rho_new - rho_full

        out_rows.append({
            "source": source,
            "vintage_year": vintage,
            "n_countries": len(index_pct),
            "rho_full": round(rho_full, 4),
            "rho_full_ci_low": round(ci_full[0], 4),
            "rho_full_ci_high": round(ci_full[1], 4),
            "rho_minus_top1": round(rho_new, 4),
            "rho_minus_top1_ci_low": round(ci_new[0], 4),
            "rho_minus_top1_ci_high": round(ci_new[1], 4),
            "delta_rho": round(delta_rho, 4),
        })
        print(f"  {source} {vintage}: n={len(index_pct)}, ρ_full={rho_full:+.3f} CI[{ci_full[0]:+.2f},{ci_full[1]:+.2f}], "
              f"ρ_minus_top1={rho_new:+.3f} CI[{ci_new[0]:+.2f},{ci_new[1]:+.2f}], Δρ={delta_rho:+.3f}")

    # Save
    out_path = PA / "table3_leave_top1_sensitivity.csv"
    with out_path.open("w") as f:
        if out_rows:
            wr = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            wr.writeheader()
            for row in out_rows:
                wr.writerow(row)
    print(f"\n✅ Written {len(out_rows)} rows → {out_path}")


if __name__ == "__main__":
    main()
