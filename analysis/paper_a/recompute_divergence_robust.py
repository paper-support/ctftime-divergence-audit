#!/usr/bin/env python3
"""T1.5 — Recompute divergence with minimum-N filter + shrinkage-adjusted CTF visibility.

Per Codex Round 13: 'raw active-team count percentile is too sensitive to small N;
small countries get inflated divergence scores. Replace with composite shrunken visibility.'

Components of CTF visibility composite (each ranked, then averaged):
  V1 = log1p(teams_per_million_internet_users)         — exposure-adjusted activity
  V2 = Wilson 95% lower bound on top50_sum / total_appearances  — quality of competition
  V3 = -log1p(ctf_median_place_avg)                    — typical rank (lower = better)
  V4 = log1p(n_events_sum)                             — participation intensity
  V5 = ctf_years_active_in_window / 3                  — temporal consistency

Inclusion criteria (Codex recommended):
  main_sample:    n_teams_max >= 5  AND n_events_sum >= 20  AND years_active >= 2
  sensitivity:    n_teams_max >= 3  AND years_active >= 1   (broader)
  unstable:       below sensitivity threshold (appendix only)

For each (source, vintage_year), recompute:
  - shrunken_ctf_visibility_pct: within-vintage percentile of composite
  - divergence_robust: shrunken_ctf_pct - index_pct
  - inclusion_tier: 'main' | 'sensitivity' | 'unstable'

Output:
  data/processed/paper_a/rq_a1_vintage_panel_robust.csv
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data" / "processed" / "paper_a"


def wilson_lower(x: int, n: int, z: float = 1.96) -> float:
    """Wilson lower 95% CI bound for proportion x/n. Returns 0 if n=0."""
    if n == 0:
        return 0.0
    # cap x at n in case of accounting double-count (e.g., multiple teams per event in country)
    x = min(x, n)
    p = x / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    inner = (p * (1 - p) + z**2 / (4 * n)) / n
    margin = z * math.sqrt(max(0.0, inner))
    return max(0.0, (centre - margin) / denom)


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
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel.csv").open()))
    print(f"Loaded {len(rows)} input rows")

    def fnum(r, k, default=None):
        v = r.get(k, "")
        if v == "" or v is None:
            return default
        try:
            return float(v)
        except ValueError:
            return default

    # ---- Group by vintage and compute composite within-vintage
    by_vintage: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        if not r.get("has_ctf") or int(r["has_ctf"]) == 0:
            r["inclusion_tier"] = "no_ctf"
            r["shrunken_ctf_visibility_pct"] = ""
            r["divergence_robust"] = ""
            continue
        by_vintage[(r["source"], int(r["vintage_year"]))].append(r)

    for (source, vintage), group in by_vintage.items():
        # ---- compute the 5 components per row
        for r in group:
            n_teams = fnum(r, "ctf_n_teams_max", 0) or 0
            n_events = fnum(r, "ctf_n_events_sum", 0) or 0
            years_active = fnum(r, "ctf_years_active_in_window", 0) or 0
            top50_sum = fnum(r, "ctf_top50_sum", 0) or 0
            total_app = fnum(r, "ctf_total_appearances_sum", 0) or 0  # team-event entries
            median_place = fnum(r, "ctf_median_place_avg", None)
            pop = fnum(r, "wb_population", None)
            int_pct = fnum(r, "wb_internet_users_pct", None)

            # internet-user population (millions)
            if pop and int_pct and int_pct > 0:
                internet_users_m = (pop * int_pct / 100) / 1e6
            else:
                internet_users_m = None

            # V1: teams per million internet users (log1p)
            if internet_users_m and internet_users_m > 0.001:
                r["v1_teams_per_million_internet_users"] = n_teams / internet_users_m
                r["v1_score"] = math.log1p(r["v1_teams_per_million_internet_users"])
            else:
                r["v1_teams_per_million_internet_users"] = ""
                r["v1_score"] = None

            # V2: Wilson lower bound on top50 share
            if total_app > 0:
                r["v2_top50_share_wilson_lower"] = wilson_lower(int(top50_sum), int(total_app))
                r["v2_score"] = r["v2_top50_share_wilson_lower"]
            else:
                r["v2_top50_share_wilson_lower"] = 0.0
                r["v2_score"] = 0.0

            # V3: median place (negated, log)
            if median_place and median_place > 0:
                r["v3_neg_log_median_place"] = -math.log1p(median_place)
                r["v3_score"] = r["v3_neg_log_median_place"]
            else:
                r["v3_neg_log_median_place"] = ""
                r["v3_score"] = None

            # V4: events count (log1p)
            r["v4_log_events"] = math.log1p(n_events)
            r["v4_score"] = r["v4_log_events"]

            # V5: years active normalized
            window_len = int(r["ctf_window_end"]) - int(r["ctf_window_start"]) + 1
            r["v5_years_active_norm"] = years_active / window_len
            r["v5_score"] = r["v5_years_active_norm"]

        # ---- Convert each component to within-vintage percentile
        for v_col in ["v1_score", "v2_score", "v3_score", "v4_score", "v5_score"]:
            vals_with_idx = [(i, r[v_col]) for i, r in enumerate(group) if r[v_col] is not None]
            if not vals_with_idx:
                for r in group:
                    r[f"{v_col}_pct"] = None
                continue
            idxs, vals = zip(*vals_with_idx)
            pcts = percentile_rank(list(vals), higher_is_better=True)
            for k, i in enumerate(idxs):
                group[i][f"{v_col}_pct"] = pcts[k]
            for r in group:
                if r[v_col] is None:
                    r[f"{v_col}_pct"] = None  # missing component

        # ---- Composite: equal-weighted average of available component percentiles
        for r in group:
            avail = [r[c] for c in [f"v{i}_score_pct" for i in range(1, 6)] if r.get(c) is not None]
            if avail:
                r["shrunken_ctf_composite"] = sum(avail) / len(avail)
                r["n_components_available"] = len(avail)
            else:
                r["shrunken_ctf_composite"] = None
                r["n_components_available"] = 0

        # ---- Within-vintage percentile of composite (renormalize)
        comp_vals = [(i, r["shrunken_ctf_composite"]) for i, r in enumerate(group)
                     if r["shrunken_ctf_composite"] is not None]
        if comp_vals:
            idxs, vals = zip(*comp_vals)
            pcts = percentile_rank(list(vals), higher_is_better=True)
            for k, i in enumerate(idxs):
                group[i]["shrunken_ctf_visibility_pct"] = pcts[k]
            for r in group:
                if "shrunken_ctf_visibility_pct" not in r:
                    r["shrunken_ctf_visibility_pct"] = None

        # ---- Inclusion tier
        for r in group:
            n_teams = fnum(r, "ctf_n_teams_max", 0) or 0
            n_events = fnum(r, "ctf_n_events_sum", 0) or 0
            years_active = fnum(r, "ctf_years_active_in_window", 0) or 0

            if n_teams >= 5 and n_events >= 20 and years_active >= 2:
                r["inclusion_tier"] = "main"
            elif n_teams >= 3 and years_active >= 1:
                r["inclusion_tier"] = "sensitivity"
            else:
                r["inclusion_tier"] = "unstable"

        # ---- Divergence robust = shrunken_ctf_pct - index_pct (when both available)
        for r in group:
            idx_pct = fnum(r, "index_percentile", None)
            sc_pct = r.get("shrunken_ctf_visibility_pct")
            if idx_pct is not None and sc_pct is not None:
                r["divergence_robust"] = round(sc_pct - idx_pct, 2)
            else:
                r["divergence_robust"] = ""

    # ---- Write enriched panel
    # Determine output columns
    sample_keys = list(rows[0].keys())
    extra_keys = [
        "v1_teams_per_million_internet_users", "v1_score_pct",
        "v2_top50_share_wilson_lower", "v2_score_pct",
        "v3_neg_log_median_place", "v3_score_pct",
        "v4_log_events", "v4_score_pct",
        "v5_years_active_norm", "v5_score_pct",
        "shrunken_ctf_composite", "n_components_available",
        "shrunken_ctf_visibility_pct", "divergence_robust",
        "inclusion_tier",
    ]
    out_keys = sample_keys + [k for k in extra_keys if k not in sample_keys]

    out_path = PA / "rq_a1_vintage_panel_robust.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            # ensure all keys exist (None → "")
            for k in out_keys:
                if k not in r or r[k] is None:
                    r[k] = ""
            w.writerow(r)
    print(f"Wrote {out_path}")

    # ---- Diagnostics
    from collections import Counter
    print("\n=== Inclusion tier × vintage ===")
    for (source, vintage), group in sorted(by_vintage.items()):
        tiers = Counter(r["inclusion_tier"] for r in group)
        print(f"  {source} {vintage}: main={tiers['main']:3d}  "
              f"sensitivity={tiers['sensitivity']:3d}  unstable={tiers['unstable']:3d}  "
              f"total={len(group)}")

    print("\n=== Robust divergence — top NEGATIVE (policy-rich/CTF-poor), MAIN sample only ===")
    for (source, vintage), group in sorted(by_vintage.items()):
        if source != "GCI":
            continue
        eligible = [r for r in group
                    if r["inclusion_tier"] == "main"
                    and r.get("divergence_robust") not in ("", None)
                    and r.get("index_percentile") not in ("", None)]
        eligible.sort(key=lambda r: float(r["divergence_robust"]))
        print(f"  --- GCI {vintage} (n_main={len(eligible)}) ---")
        for r in eligible[:5]:
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:28]:28s}) "
                  f"idx_pct={float(r['index_percentile']):>5.1f} "
                  f"shrunken_ctf_pct={float(r['shrunken_ctf_visibility_pct']):>5.1f} "
                  f"div_robust={float(r['divergence_robust']):>6.1f}  "
                  f"n_teams={int(float(r['ctf_n_teams_max']))}")

    print("\n=== Robust divergence — top POSITIVE (CTF-rich/policy-light), MAIN sample only ===")
    for (source, vintage), group in sorted(by_vintage.items()):
        if source != "GCI":
            continue
        eligible = [r for r in group
                    if r["inclusion_tier"] == "main"
                    and r.get("divergence_robust") not in ("", None)
                    and r.get("index_percentile") not in ("", None)]
        eligible.sort(key=lambda r: -float(r["divergence_robust"]))
        print(f"  --- GCI {vintage} (n_main={len(eligible)}) ---")
        for r in eligible[:5]:
            print(f"    {r['iso2']:3s} ({r['canonical_name'][:28]:28s}) "
                  f"idx_pct={float(r['index_percentile']):>5.1f} "
                  f"shrunken_ctf_pct={float(r['shrunken_ctf_visibility_pct']):>5.1f} "
                  f"div_robust={float(r['divergence_robust']):>6.1f}  "
                  f"n_teams={int(float(r['ctf_n_teams_max']))}")


if __name__ == "__main__":
    main()
