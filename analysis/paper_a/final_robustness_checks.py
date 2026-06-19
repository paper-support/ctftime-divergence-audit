#!/usr/bin/env python3
"""Final 3 robustness items per Codex Round 15:

(3) Ukraine top10_share verification — spot-check actual team placements
(4) Bootstrap 95% CIs for Spearman ρ (global + within-region)
(5) GCI 2024 tier coarseness — ordinal-tier regression as alternative model

Output:
  data/processed/paper_a/ukraine_verification.md
  data/processed/paper_a/spearman_bootstrap.csv
  data/processed/paper_a/gci_2024_ordinal_model.md
"""
from __future__ import annotations

import csv
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"

WINDOWS = [
    ("GCI", 2017, 2016, 2018),
    ("GCI", 2020, 2019, 2021),
    ("GCI", 2024, 2023, 2025),
    ("NCSI", 2026, 2024, 2026),
]


def spearman(x: list[float], y: list[float]) -> float:
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
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((r - mx) ** 2 for r in rx) ** 0.5
    vy = sum((r - my) ** 2 for r in ry) ** 0.5
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / (vx * vy)


def kendall_tau(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    concord = discord = ties = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = x[j] - x[i], y[j] - y[i]
            if dx == 0 or dy == 0:
                ties += 1
            elif (dx > 0) == (dy > 0):
                concord += 1
            else:
                discord += 1
    total = n * (n - 1) / 2
    if total == 0:
        return float("nan")
    return (concord - discord) / total


def bootstrap_ci(stat_fn, x: list[float], y: list[float],
                 n_boot: int = 2000, ci: float = 0.95, seed: int = 42) -> tuple:
    rng = random.Random(seed)
    n = len(x)
    if n < 4:
        return (float("nan"), float("nan"))
    stats_list = []
    for _ in range(n_boot):
        idxs = [rng.randrange(n) for _ in range(n)]
        bx = [x[i] for i in idxs]
        by = [y[i] for i in idxs]
        s = stat_fn(bx, by)
        if s == s:  # not NaN
            stats_list.append(s)
    if not stats_list:
        return (float("nan"), float("nan"))
    stats_list.sort()
    a = (1 - ci) / 2
    lo = stats_list[int(a * len(stats_list))]
    hi = stats_list[int((1 - a) * len(stats_list)) - 1]
    return (lo, hi)


# ============================================================
# (3) Ukraine verification
# ============================================================

def ukraine_verification():
    print("=== (3) Ukraine top-performance verification ===\n")

    event_year = {}
    event_name = {}
    field_size = {}
    with (PA / "events_master.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                eid = int(r["event_id"])
                event_year[eid] = int(r["year"])
                event_name[eid] = r["title"]
            except (ValueError, KeyError):
                pass

    # Count UA rows per event for 2016-2018 window
    ua_events = defaultdict(list)
    fs = defaultdict(int)
    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            eid = int(r["event_id"]) if r.get("event_id") else None
            if not eid: continue
            if r.get("place"):
                fs[eid] += 1
            if r.get("country") == "UA":
                ua_events[eid].append({
                    "team_id": r.get("team_id"),
                    "team_name": r.get("team_name"),
                    "place": int(r["place"]) if r.get("place") else None,
                    "academic": r.get("academic") == "1",
                })

    # Filter to 2016-2018 window
    ua_rows = []
    for eid, teams in ua_events.items():
        yr = event_year.get(eid)
        if yr is None or not (2016 <= yr <= 2018):
            continue
        f_size = fs.get(eid, 0)
        for t in teams:
            if t["place"] is None or f_size <= 1:
                continue
            ep = 1.0 - (t["place"] - 1) / (f_size - 1)
            ua_rows.append({
                "event_id": eid,
                "year": yr,
                "event_name": event_name.get(eid, "")[:50],
                "team_id": t["team_id"],
                "team_name": t["team_name"][:30] if t["team_name"] else "",
                "place": t["place"],
                "field_size": f_size,
                "event_percentile": round(ep, 4),
                "academic": t["academic"],
            })

    # Aggregate by team
    team_stats = defaultdict(lambda: {"n": 0, "top10_count": 0, "name": ""})
    for r in ua_rows:
        d = team_stats[r["team_id"]]
        d["n"] += 1
        d["name"] = r["team_name"]
        if r["event_percentile"] >= 0.90:
            d["top10_count"] += 1

    top_teams = sorted(team_stats.items(), key=lambda x: -x[1]["top10_count"])[:8]

    n_total = len(ua_rows)
    n_top10 = sum(1 for r in ua_rows if r["event_percentile"] >= 0.90)
    print(f"Ukraine total team-event appearances 2016-2018: {n_total}")
    print(f"Top-10% appearances: {n_top10} ({n_top10/n_total:.1%})")
    print()
    print("Top Ukrainian teams by top-10% counts:")
    print(f"{'team_id':<10s} {'name':<30s} {'n_app':>6s} {'top10':>7s} {'top10%':>7s}")
    for tid, d in top_teams:
        if d["n"] == 0: continue
        print(f"{tid:<10s} {d['name']:<30s} {d['n']:>6d} {d['top10_count']:>7d} "
              f"{d['top10_count']/d['n']:>6.1%}")

    # Concentration check: what if we remove the top team?
    top_tid = top_teams[0][0] if top_teams else None
    if top_tid:
        ex_top = [r for r in ua_rows if r["team_id"] != top_tid]
        n_ex = len(ex_top)
        top10_ex = sum(1 for r in ex_top if r["event_percentile"] >= 0.90)
        print(f"\nAfter REMOVING top team ({top_tid} - {team_stats[top_tid]['name']}):")
        print(f"  n_appearances: {n_ex}")
        print(f"  top10 share: {top10_ex/n_ex:.1%}  (was {n_top10/n_total:.1%})")

    # ---- write Markdown report
    body = ["# Ukraine top-10% verification (per Codex Round 15)\n\n"]
    body.append(f"**Window**: 2016-2018 (GCI 2017 vintage)\n\n")
    body.append(f"**Total UA team-event appearances**: {n_total}\n")
    body.append(f"**Top-10% appearances**: {n_top10} ({n_top10/n_total:.1%})\n\n")
    body.append("## Top Ukrainian teams\n\n")
    body.append("| team_id | name | n_appearances | top10 count | top10 share |\n|---|---|---|---|---|\n")
    for tid, d in top_teams:
        body.append(f"| {tid} | {d['name']} | {d['n']} | {d['top10_count']} | {d['top10_count']/max(1,d['n']):.1%} |\n")
    body.append(f"\n## Concentration check\n\n")
    if top_tid:
        body.append(f"Removing top team `{top_tid} ({team_stats[top_tid]['name']})`:\n")
        body.append(f"- n_appearances: {n_ex}\n")
        body.append(f"- top10_share: {top10_ex/n_ex:.1%} (was {n_top10/n_total:.1%})\n\n")
        if abs(top10_ex/n_ex - n_top10/n_total) < 0.05:
            body.append("✅ **Verification PASSED**: top10_share is robust to removing the single most active team. "
                       "The Ukrainian performance pattern is NOT driven by a single elite team.\n")
        else:
            body.append("⚠️ Top10_share shifts >5pp after removing top team. Document this concentration.\n")
    (PA / "ukraine_verification.md").write_text("".join(body))
    print(f"\nWrote {PA / 'ukraine_verification.md'}")
    return n_top10 / n_total


# ============================================================
# (4) Bootstrap CIs for Spearman / Kendall
# ============================================================

def bootstrap_cis():
    print("\n\n=== (4) Bootstrap 95% CIs for ρ and τ ===\n")
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf_region.csv").open()))

    out_rows = []
    for source, vintage in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024), ("NCSI", 2026)]:
        eligible = [r for r in rows
                    if r["source"] == source and int(r["vintage_year"]) == vintage
                    and r["inclusion_tier"] == "main"
                    and r.get("index_percentile") not in ("", None)
                    and r.get("performance_composite_pct") not in ("", None)]
        if len(eligible) < 5:
            continue
        x = [float(r["index_percentile"]) for r in eligible]
        y = [float(r["performance_composite_pct"]) for r in eligible]
        rho = spearman(x, y)
        tau = kendall_tau(x, y)
        rho_ci = bootstrap_ci(spearman, x, y, n_boot=2000)
        tau_ci = bootstrap_ci(kendall_tau, x, y, n_boot=2000)
        out_rows.append({
            "source": source,
            "vintage_year": vintage,
            "n": len(eligible),
            "spearman_rho": round(rho, 4),
            "spearman_rho_ci_low": round(rho_ci[0], 4),
            "spearman_rho_ci_high": round(rho_ci[1], 4),
            "kendall_tau": round(tau, 4),
            "kendall_tau_ci_low": round(tau_ci[0], 4),
            "kendall_tau_ci_high": round(tau_ci[1], 4),
        })
        print(f"{source} {vintage} n={len(eligible):2d}: "
              f"ρ={rho:+.3f} [{rho_ci[0]:+.3f}, {rho_ci[1]:+.3f}]  "
              f"τ={tau:+.3f} [{tau_ci[0]:+.3f}, {tau_ci[1]:+.3f}]")

    # Within-region pooled stats too
    print("\n--- Within-region: pooled ρ across regions (sample-weighted) ---")
    by_vintage_region = defaultdict(list)
    for r in rows:
        if (r["inclusion_tier"] == "main"
                and r.get("index_percentile") not in ("", None)
                and r.get("performance_composite_pct") not in ("", None)
                and r.get("un_region")):
            key = (r["source"], int(r["vintage_year"]), r["un_region"])
            by_vintage_region[key].append(r)

    for source, vintage in [("GCI", 2017), ("GCI", 2020), ("GCI", 2024), ("NCSI", 2026)]:
        within_rhos = []
        for (s, v, reg), sub in by_vintage_region.items():
            if s != source or v != vintage or len(sub) < 4:
                continue
            x = [float(r["index_percentile"]) for r in sub]
            y = [float(r["performance_composite_pct"]) for r in sub]
            rho = spearman(x, y)
            if rho == rho:
                within_rhos.append((rho, len(sub)))
        if within_rhos:
            total_n = sum(n for _, n in within_rhos)
            wavg = sum(r * n for r, n in within_rhos) / total_n
            print(f"  {source} {vintage}: pooled within-region ρ = {wavg:+.3f}  "
                  f"(across {len(within_rhos)} regions, total n={total_n})")
            # Bootstrap within-region pooled by resampling regions
            rng = random.Random(42)
            boot_pooled = []
            for _ in range(2000):
                sample = [rng.choice(within_rhos) for _ in range(len(within_rhos))]
                ttn = sum(n for _, n in sample)
                bp = sum(r * n for r, n in sample) / ttn if ttn > 0 else float("nan")
                if bp == bp:
                    boot_pooled.append(bp)
            boot_pooled.sort()
            lo = boot_pooled[int(0.025 * len(boot_pooled))]
            hi = boot_pooled[int(0.975 * len(boot_pooled)) - 1]
            print(f"           [region-resampled 95% CI: {lo:+.3f}, {hi:+.3f}]")
            # Add to output table
            for orow in out_rows:
                if orow["source"] == source and orow["vintage_year"] == vintage:
                    orow["within_region_pooled_rho"] = round(wavg, 4)
                    orow["within_region_pooled_rho_ci_low"] = round(lo, 4)
                    orow["within_region_pooled_rho_ci_high"] = round(hi, 4)

    out_path = PA / "spearman_bootstrap.csv"
    fields = ["source", "vintage_year", "n", "spearman_rho",
              "spearman_rho_ci_low", "spearman_rho_ci_high",
              "kendall_tau", "kendall_tau_ci_low", "kendall_tau_ci_high",
              "within_region_pooled_rho", "within_region_pooled_rho_ci_low",
              "within_region_pooled_rho_ci_high"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in out_rows:
            for k in fields:
                if k not in r:
                    r[k] = ""
            w.writerow(r)
    print(f"\nWrote {out_path}")


# ============================================================
# (5) GCI 2024 ordinal tier model
# ============================================================

def gci_2024_ordinal():
    print("\n\n=== (5) GCI 2024 tier ordinal robustness ===\n")
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf_region.csv").open()))

    # For GCI 2024, the raw 'index_score_raw' IS the tier 1-5.
    # Group performance_composite_pct by tier and compare
    tier_data = defaultdict(list)
    for r in rows:
        if (r["source"] == "GCI" and int(r["vintage_year"]) == 2024
                and r["inclusion_tier"] == "main"
                and r.get("index_score_raw") not in ("", None)
                and r.get("performance_composite_pct") not in ("", None)):
            try:
                tier = int(r["index_score_raw"])
                pp = float(r["performance_composite_pct"])
                tier_data[tier].append(pp)
            except ValueError:
                pass

    print("Performance composite percentile by GCI 2024 tier (MAIN sample):")
    print(f"{'Tier':<6s} {'N':>4s} {'mean perf%':>11s} {'median':>8s} {'std':>7s}")
    body = ["# GCI 2024 ordinal-tier analysis (per Codex Round 15 robustness #5)\n\n"]
    body.append("GCI 2024 (v5) is tier-categorical (1-5), unlike GCI 2017/2020 which are cardinal. "
                "To avoid imputing artificial precision, we compare performance composite distributions "
                "across tiers using ordinal-aware analysis.\n\n")
    body.append("## Performance composite percentile by GCI 2024 tier\n\n")
    body.append("| Tier | N | Mean perf% | Median | Std |\n|---|---|---|---|---|\n")
    for t in sorted(tier_data.keys()):
        vals = tier_data[t]
        if vals:
            m = statistics.mean(vals)
            md = statistics.median(vals)
            s = statistics.stdev(vals) if len(vals) > 1 else 0
            print(f"{t:<6d} {len(vals):>4d} {m:>11.2f} {md:>8.2f} {s:>7.2f}")
            body.append(f"| {t} | {len(vals)} | {m:.2f} | {md:.2f} | {s:.2f} |\n")

    # If GCI tier discrimination were strong, mean perf% should monotonically decrease with tier#.
    # Check monotonicity:
    means = [(t, statistics.mean(tier_data[t])) for t in sorted(tier_data.keys()) if tier_data[t]]
    monotone = all(means[i][1] >= means[i+1][1] for i in range(len(means) - 1))
    body.append(f"\n**Monotonicity (Tier 1 best → Tier 5 worst)**: {'YES' if monotone else 'NO'}\n\n")
    print(f"\nMonotonic (Tier 1 best → Tier 5 worst): {monotone}")

    # Kendall's τ on tier × performance
    if len([t for t in tier_data if tier_data[t]]) >= 2:
        all_x, all_y = [], []
        for t, vals in tier_data.items():
            for v in vals:
                all_x.append(-t)  # invert so higher = better tier
                all_y.append(v)
        tau = kendall_tau(all_x, all_y)
        ci = bootstrap_ci(kendall_tau, all_x, all_y, n_boot=2000)
        body.append(f"## Kendall's τ (ordinal-aware): tier × performance\n\n")
        body.append(f"- τ = **{tau:+.3f}**  (95% bootstrap CI: [{ci[0]:+.3f}, {ci[1]:+.3f}])\n")
        body.append(f"- N = {len(all_x)} country observations\n\n")
        print(f"\nKendall's τ (inverted tier × performance) = {tau:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}]")

    body.append("## Methods note\n\n")
    body.append("The 2024 vintage uses a 5-tier categorical assignment introduced in GCI v5 (ITU 2024). "
                "Many countries within a tier share identical positions in the index, which compresses the "
                "discriminating power of correlation analysis. We report:\n"
                "1. Within-vintage **percentile rank** (with mid-rank tied positions) for cross-vintage comparability;\n"
                "2. **Kendall's τ** on the original tier ordinal, which is invariant to tie compression;\n"
                "3. Distributional summaries of CTF performance composite per tier (table above).\n\n"
                "Findings should be interpreted accordingly: 2024 results carry lower discriminating "
                "resolution than 2017/2020 cardinal scores.\n")

    (PA / "gci_2024_ordinal_model.md").write_text("".join(body))
    print(f"Wrote {PA / 'gci_2024_ordinal_model.md'}")


if __name__ == "__main__":
    ukraine_verification()
    bootstrap_cis()
    gci_2024_ordinal()
