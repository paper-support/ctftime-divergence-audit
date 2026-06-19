#!/usr/bin/env python3
"""Round 15 follow-up: region M49 FE + academic-vs-non-academic subset robustness.

Per Codex Round 15:
- Mandatory robustness #1: region FE / within-region divergence ranks
- Mandatory robustness #2: academic-only vs non-academic-only subset

Adds to rq_a1_vintage_panel_robust_perf:
- continent, un_region (M49 subregion)
- within_region_index_pct, within_region_performance_pct
- within_region_divergence_performance

Builds subset panels:
- rq_a1_vintage_panel_academic_only.csv
- rq_a1_vintage_panel_non_academic.csv

Output:
- countries_canonical_v2.csv (with continent + UN_region)
- rq_a1_vintage_panel_robust_perf_region.csv (with within-region columns)
- rq_a1_subset_robustness_report.md (academic vs non-academic comparison)
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import country_converter as coco

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"


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


def spearman(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation coefficient."""
    n = len(x)
    if n < 2:
        return float("nan")

    def ranks(vals):
        idx = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[idx[j + 1]] == vals[idx[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[idx[k]] = avg_rank
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((r - mx) ** 2 for r in rx) ** 0.5
    vy = sum((r - my) ** 2 for r in ry) ** 0.5
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / (vx * vy)


def main():
    # ---- 1. Build country → region mapping
    cc = coco.CountryConverter().data
    iso2_to_region = {}
    for _, r in cc.iterrows():
        iso2 = r.get("ISO2")
        if isinstance(iso2, str) and len(iso2) == 2:
            iso2_to_region[iso2] = {
                "continent": r.get("continent", ""),
                "un_region": r.get("UNregion", ""),
            }

    # ---- 2. Enrich canonical countries CSV
    canon_rows = list(csv.DictReader((PA / "countries_canonical.csv").open()))
    for r in canon_rows:
        reg = iso2_to_region.get(r["iso2"], {})
        r["continent"] = reg.get("continent", "")
        r["un_region"] = reg.get("un_region", "")
    fields = list(canon_rows[0].keys())
    with (PA / "countries_canonical_v2.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(canon_rows)
    print(f"Wrote countries_canonical_v2.csv with continent + un_region")

    iso2_canon = {r["iso2"]: r for r in canon_rows}

    # ---- 3. Load main analysis panel and add region columns
    panel = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf.csv").open()))
    for r in panel:
        cinfo = iso2_canon.get(r["iso2"], {})
        r["continent"] = cinfo.get("continent", "")
        r["un_region"] = cinfo.get("un_region", "")

    # ---- 4. Compute within-region percentile (per source-vintage-region group)
    # Only for MAIN sample rows that have both index and performance
    by_vintage_region = defaultdict(list)
    for r in panel:
        if (r["inclusion_tier"] == "main"
                and r.get("index_percentile") not in ("", None)
                and r.get("performance_composite_pct") not in ("", None)
                and r["un_region"]):
            key = (r["source"], int(r["vintage_year"]), r["un_region"])
            by_vintage_region[key].append(r)

    for key, group in by_vintage_region.items():
        # Only meaningful if region has >=3 countries
        if len(group) < 3:
            for r in group:
                r["within_region_index_pct"] = ""
                r["within_region_performance_pct"] = ""
                r["within_region_divergence"] = ""
            continue
        idx_vals = [float(r["index_percentile"]) for r in group]
        perf_vals = [float(r["performance_composite_pct"]) for r in group]
        idx_pcts = percentile_rank(idx_vals, higher_is_better=True)
        perf_pcts = percentile_rank(perf_vals, higher_is_better=True)
        for r, ip, pp in zip(group, idx_pcts, perf_pcts):
            r["within_region_index_pct"] = ip
            r["within_region_performance_pct"] = pp
            r["within_region_divergence"] = round(pp - ip, 2)

    # Fill defaults for rows without within-region calc
    for r in panel:
        for k in ["within_region_index_pct", "within_region_performance_pct", "within_region_divergence"]:
            if k not in r:
                r[k] = ""

    # ---- 5. Write region-enriched panel
    out_panel = PA / "rq_a1_vintage_panel_robust_perf_region.csv"
    fields = list(panel[0].keys())
    with out_panel.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(panel)
    print(f"Wrote {out_panel}")

    # ---- 6. Global vs within-region Spearman comparison
    print("\n=== Spearman ρ: global vs within-region (using MAIN sample) ===")
    print(f"{'source':<6s} {'vintage':<8s} {'n':>4s} {'ρ(idx,perf)':>14s} {'avg(within-reg)':>18s}")
    for source in ["GCI", "NCSI"]:
        for vintage in [2017, 2020, 2024, 2026]:
            if (source, vintage) not in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024), ("NCSI", 2026)]:
                continue
            rows = [r for r in panel
                    if r["source"] == source and int(r["vintage_year"]) == vintage
                    and r["inclusion_tier"] == "main"
                    and r.get("index_percentile") not in ("", None)
                    and r.get("performance_composite_pct") not in ("", None)]
            if len(rows) < 4:
                continue
            global_rho = spearman(
                [float(r["index_percentile"]) for r in rows],
                [float(r["performance_composite_pct"]) for r in rows],
            )

            # within-region: per-region spearman, then sample-weighted average
            by_reg = defaultdict(list)
            for r in rows:
                if r["un_region"]:
                    by_reg[r["un_region"]].append(r)
            within_rhos = []
            for reg, sub in by_reg.items():
                if len(sub) >= 4:
                    rho = spearman(
                        [float(r["index_percentile"]) for r in sub],
                        [float(r["performance_composite_pct"]) for r in sub],
                    )
                    if rho == rho:  # not NaN
                        within_rhos.append((rho, len(sub)))
            if within_rhos:
                total_n = sum(n for _, n in within_rhos)
                wavg = sum(rho * n for rho, n in within_rhos) / total_n
            else:
                wavg = float("nan")
            print(f"{source:<6s} {vintage:<8d} {len(rows):>4d} {global_rho:>14.3f} {wavg:>18.3f}")

    # ---- 7. Top stable within-region outliers
    print("\n=== Top WITHIN-REGION negative divergence (after region adj), MAIN sample ===")
    for source, vintage in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024)]:
        eligible = [r for r in panel
                    if r["source"] == source and int(r["vintage_year"]) == vintage
                    and r["inclusion_tier"] == "main"
                    and r.get("within_region_divergence") not in ("", None)]
        eligible.sort(key=lambda r: float(r["within_region_divergence"]) if r["within_region_divergence"] != "" else 0)
        print(f"\n  --- GCI {vintage} ---")
        for r in eligible[:5]:
            d = float(r["within_region_divergence"]) if r["within_region_divergence"] != "" else 0
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:22]:22s}) reg={r['un_region'][:18]:18s} "
                  f"within_reg_idx_pct={float(r['within_region_index_pct']):>5.1f} "
                  f"within_reg_perf_pct={float(r['within_region_performance_pct']):>5.1f} "
                  f"div={d:>+6.1f}")

    print("\n=== Top WITHIN-REGION positive divergence ===")
    for source, vintage in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024)]:
        eligible = [r for r in panel
                    if r["source"] == source and int(r["vintage_year"]) == vintage
                    and r["inclusion_tier"] == "main"
                    and r.get("within_region_divergence") not in ("", None)]
        eligible.sort(key=lambda r: -float(r["within_region_divergence"]) if r["within_region_divergence"] != "" else 0)
        print(f"\n  --- GCI {vintage} ---")
        for r in eligible[:5]:
            d = float(r["within_region_divergence"]) if r["within_region_divergence"] != "" else 0
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:22]:22s}) reg={r['un_region'][:18]:18s} "
                  f"within_reg_idx_pct={float(r['within_region_index_pct']):>5.1f} "
                  f"within_reg_perf_pct={float(r['within_region_performance_pct']):>5.1f} "
                  f"div={d:>+6.1f}")

    # ---- 8. Academic-only vs non-academic-only subset analysis
    # Need to recompute composite using only academic-flagged team-event rows or only non-academic
    print("\n=== Academic-only vs Non-academic-only subset (top 5 +/- divergence per vintage) ===")

    # Load event_scores_enriched and split by academic flag
    event_year = {}
    with (PA / "events_master.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                event_year[int(r["event_id"])] = int(r["year"])
            except (ValueError, KeyError):
                pass

    # field size per event
    field_size = defaultdict(int)
    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            if r.get("place") and r.get("event_id"):
                field_size[int(r["event_id"])] += 1

    # window mapping
    WINDOWS = [
        ("GCI", 2017, 2016, 2018),
        ("GCI", 2020, 2019, 2021),
        ("GCI", 2024, 2023, 2025),
        ("NCSI", 2026, 2024, 2026),
    ]
    win_lookup = {}
    for source, vintage, ws, we in WINDOWS:
        for y in range(ws, we + 1):
            win_lookup.setdefault(y, []).append((source, vintage))

    # Build subset performance metrics
    subsets = {"academic": defaultdict(lambda: {"appearances": 0, "percentiles": [], "top10": 0}),
               "non_academic": defaultdict(lambda: {"appearances": 0, "percentiles": [], "top10": 0})}

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
            fs = field_size.get(eid, 0)
            if not yr or fs <= 1 or place < 1 or place > fs:
                continue
            ep = 1.0 - (place - 1) / (fs - 1)
            is_acad = r.get("academic", "") == "1"
            tier_key = "academic" if is_acad else "non_academic"
            for (source, vintage) in win_lookup.get(yr, []):
                key = (country, source, vintage)
                subsets[tier_key][key]["appearances"] += 1
                subsets[tier_key][key]["percentiles"].append(ep)
                if ep >= 0.90:
                    subsets[tier_key][key]["top10"] += 1

    # Compute composite per subset
    subset_rows = []
    for tier_key in ["academic", "non_academic"]:
        for (country, source, vintage), d in subsets[tier_key].items():
            n = d["appearances"]
            if n < 5:  # min-N for subset
                continue
            subset_rows.append({
                "iso2": country,
                "source": source,
                "vintage_year": vintage,
                "subset": tier_key,
                "appearances": n,
                "median_event_percentile": round(statistics.median(d["percentiles"]), 4),
                "top10_pct_share": round(d["top10"] / n, 4),
            })

    # Within-vintage-subset percentile
    by_vs = defaultdict(list)
    for r in subset_rows:
        by_vs[(r["source"], r["vintage_year"], r["subset"])].append(r)

    for key, group in by_vs.items():
        if len(group) < 3:
            continue
        for metric in ["median_event_percentile", "top10_pct_share"]:
            vals = [r[metric] for r in group]
            pcts = percentile_rank(vals, higher_is_better=True)
            for r, p in zip(group, pcts):
                r[f"{metric}_pct"] = p
        for r in group:
            r["subset_perf_composite_pct"] = round(
                (r["median_event_percentile_pct"] + r["top10_pct_share_pct"]) / 2, 2)

    # Join with index percentile
    idx_lookup = {}
    for r in panel:
        if r.get("index_percentile") not in ("", None):
            idx_lookup[(r["iso2"], r["source"], int(r["vintage_year"]))] = float(r["index_percentile"])

    for r in subset_rows:
        idx_pct = idx_lookup.get((r["iso2"], r["source"], r["vintage_year"]))
        if idx_pct is not None and "subset_perf_composite_pct" in r:
            r["index_percentile"] = idx_pct
            r["subset_divergence"] = round(r["subset_perf_composite_pct"] - idx_pct, 2)
        else:
            r["index_percentile"] = ""
            r["subset_divergence"] = ""

    out_subset = PA / "rq_a1_subset_robustness.csv"
    if subset_rows:
        all_keys = set()
        for r in subset_rows:
            all_keys.update(r.keys())
        fields = sorted(all_keys)
        with out_subset.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(subset_rows)
        print(f"Wrote {out_subset} ({len(subset_rows)} rows)")

    # Compare divergence consistency
    for source, vintage in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024)]:
        for tier_key in ["academic", "non_academic"]:
            rows = [r for r in subset_rows
                    if r["source"] == source and r["vintage_year"] == vintage
                    and r["subset"] == tier_key
                    and r.get("subset_divergence") not in ("", None)]
            rows.sort(key=lambda r: float(r["subset_divergence"]))
            if not rows:
                continue
            print(f"\n  {tier_key.upper()} subset — GCI {vintage} (n={len(rows)}):")
            print(f"    Top 3 NEGATIVE:")
            for r in rows[:3]:
                print(f"      {r['iso2']:3s} div={float(r['subset_divergence']):>+6.1f} "
                      f"n_app={r['appearances']} med_ep={r['median_event_percentile']:.3f} top10={r['top10_pct_share']:.3f}")
            print(f"    Top 3 POSITIVE:")
            for r in rows[-3:][::-1]:
                print(f"      {r['iso2']:3s} div={float(r['subset_divergence']):>+6.1f} "
                      f"n_app={r['appearances']} med_ep={r['median_event_percentile']:.3f} top10={r['top10_pct_share']:.3f}")


if __name__ == "__main__":
    main()
