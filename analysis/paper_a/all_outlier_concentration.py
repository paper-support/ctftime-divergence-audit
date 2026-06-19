#!/usr/bin/env python3
"""M5 — Concentration audit for headline divergence outliers.

Per Codex Round 32 design:

POSITIVE outliers (Ukraine, Argentina, Czechia): compute concentration profile
  PLUS after-removal divergence (top-1 main, top-3 sensitivity).
NEGATIVE outliers (Malaysia, Saudi Arabia, Thailand): concentration profile only.

For positive outliers we recompute the country's within-vintage performance
composite percentile after excluding the top-1 (and top-3) most active teams,
then re-rank the country against the unchanged peer set.

Output:
  data/processed/paper_a/outlier_concentration_audit.csv
  paper/paper_a/concentration_appendix.md (rendered Appendix A)
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"

# Outlier roster per Codex Round 19/20/32. Pattern: "positive" or "negative".
OUTLIERS = {
    "UA": "positive",  # Ukraine
    "AR": "positive",  # Argentina
    "CZ": "positive",  # Czechia (optional but Codex confirmed)
    "MY": "negative",  # Malaysia
    "SA": "negative",  # Saudi Arabia
    "TH": "negative",  # Thailand
}

WINDOWS = [
    ("GCI", 2017, 2016, 2018),
    ("GCI", 2020, 2019, 2021),
    ("GCI", 2024, 2023, 2025),
]


# ---------- Helpers

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


# ---------- Data loading

def load_event_years() -> dict[int, int]:
    yr = {}
    with (PA / "events_master.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                yr[int(r["event_id"])] = int(r["year"])
            except (ValueError, KeyError):
                pass
    return yr


def load_field_sizes() -> dict[int, int]:
    fs = defaultdict(int)
    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            if r.get("event_id") and r.get("place"):
                fs[int(r["event_id"])] += 1
    return dict(fs)


def load_country_appearances(field_size: dict[int, int],
                              event_year: dict[int, int]):
    """Stream event_scores_enriched and bucket by (country, vintage, team_id) with placement details."""
    win_lookup = {}
    for source, vintage, ws, we in WINDOWS:
        for y in range(ws, we + 1):
            win_lookup.setdefault(y, []).append((source, vintage))

    # appearances[(country, vintage)][team_id] = list of (event_percentile, place)
    appearances = defaultdict(lambda: defaultdict(list))
    team_names = {}

    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            country = r.get("country", "")
            if country not in OUTLIERS:
                continue
            place_s = r.get("place", "")
            eid_s = r.get("event_id", "")
            tid_s = r.get("team_id", "")
            if not country or not place_s or not eid_s or not tid_s:
                continue
            eid = int(eid_s)
            place = int(place_s)
            tid = int(tid_s)
            yr = event_year.get(eid)
            if yr is None:
                continue
            fs = field_size.get(eid, 0)
            if fs <= 1 or place < 1 or place > fs:
                continue
            ep = 1.0 - (place - 1) / (fs - 1)
            for (source, vintage) in win_lookup.get(yr, []):
                appearances[(country, source, vintage)][tid].append((ep, place))
                if tid not in team_names and r.get("team_name"):
                    team_names[tid] = r["team_name"]

    return appearances, team_names


def load_baseline_panel():
    """Load full main-sample panel; we need every country's V_cv to re-rank after removal."""
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf_region.csv").open()))
    by_vintage = defaultdict(list)
    for r in rows:
        if (r.get("inclusion_tier") == "main"
                and r.get("performance_composite_pct") not in ("", None)
                and r.get("index_percentile") not in ("", None)):
            by_vintage[(r["source"], int(r["vintage_year"]))].append(r)
    return by_vintage


# ---------- Composite & re-rank logic

def compute_country_metrics_from_appearances(team_data: dict[int, list[tuple]]) -> dict:
    """Given {team_id: [(event_pct, place), ...]}, compute country aggregate metrics."""
    all_eps = []
    n_top10 = n_top25 = n_top50 = 0
    for tid, entries in team_data.items():
        for ep, _ in entries:
            all_eps.append(ep)
            if ep >= 0.90: n_top10 += 1
            if ep >= 0.75: n_top25 += 1
            if ep >= 0.50: n_top50 += 1
    n = len(all_eps)
    if n == 0:
        return None
    return {
        "n_appearances": n,
        "median_event_percentile": statistics.median(all_eps),
        "top10_share": n_top10 / n,
        "top25_share": n_top25 / n,
        "top50_share": n_top50 / n,
    }


def country_composite_from_metrics(metrics: dict, vintage_group: list[dict],
                                    iso2: str) -> tuple[float, float]:
    """Recompute country's performance_composite_pct after replacing its metrics.

    Within-vintage percentile is recomputed against the original peer set, using
    the country's NEW metrics in place of its original metrics. Other countries'
    metrics are held fixed (so their percentile ranks shift only because of the
    target country's rank change).

    Returns (new_performance_composite_pct, new_divergence_performance).
    """
    # Build aligned arrays of 4 metrics per peer country (use existing in panel rows)
    peers = [r for r in vintage_group if r["iso2"] != iso2]
    if not peers:
        return float("nan"), float("nan")

    metric_keys_panel = [
        "median_event_percentile",
        "top10_pct_share",
        "top25_pct_share",
        "top50_pct_share",
    ]
    metric_keys_new = [
        "median_event_percentile",
        "top10_share",
        "top25_share",
        "top50_share",
    ]

    component_pcts = []
    for pk, nk in zip(metric_keys_panel, metric_keys_new):
        peer_vals = [float(r[pk]) for r in peers]
        new_val = metrics[nk]
        combined = peer_vals + [new_val]
        ranks = percentile_rank(combined, higher_is_better=True)
        component_pcts.append(ranks[-1])  # last element is the target country

    new_composite_raw = sum(component_pcts) / len(component_pcts)

    # Within-vintage percentile of the new composite among peer composites
    peer_comps = [float(r["performance_composite_raw"]) for r in peers]
    combined = peer_comps + [new_composite_raw]
    final_ranks = percentile_rank(combined, higher_is_better=True)
    new_perf_pct = final_ranks[-1]

    # New divergence vs the country's own index_percentile (unchanged)
    country_row = next(r for r in vintage_group if r["iso2"] == iso2)
    idx_pct = float(country_row["index_percentile"])
    new_div = new_perf_pct - idx_pct

    return new_perf_pct, new_div


def remove_top_n_teams(team_data: dict[int, list[tuple]], n: int) -> dict[int, list[tuple]]:
    """Return a new team_data dict with the n most-active teams removed."""
    sorted_teams = sorted(team_data.items(), key=lambda kv: -len(kv[1]))
    to_remove = {tid for tid, _ in sorted_teams[:n]}
    return {tid: entries for tid, entries in team_data.items() if tid not in to_remove}


# ---------- Main

def main():
    print("Loading event years and field sizes...")
    event_year = load_event_years()
    field_size = load_field_sizes()
    print(f"  {len(event_year):,} events; {len(field_size):,} with parsed scoreboards")

    print("Streaming country appearances for outliers...")
    appearances, team_names = load_country_appearances(field_size, event_year)
    print(f"  {len(appearances)} (country, vintage) cells loaded; {len(team_names):,} unique team names")

    print("Loading baseline panel for re-ranking...")
    baseline = load_baseline_panel()
    for (s, v), rows in baseline.items():
        print(f"  {s} {v}: {len(rows)} main-sample countries")

    out_rows = []
    for (country, source, vintage), team_data in sorted(appearances.items()):
        # Verify country is in main sample for this vintage
        vintage_group = baseline.get((source, vintage), [])
        country_row = next((r for r in vintage_group if r["iso2"] == country), None)
        if country_row is None:
            # Country may be sensitivity-tier in this vintage; skip
            continue

        n_unique = len(team_data)
        all_appearances = []
        for entries in team_data.values():
            all_appearances.extend(entries)
        total_app = len(all_appearances)
        if total_app == 0:
            continue

        # Concentration metrics
        # Note: top1/top2/top3 are defined by APPEARANCE COUNT (not by performance quality).
        # The removal logic below uses this same "most-active team" definition.
        # We additionally report the top1 team's top10 contribution as a sanity check.
        team_shares = sorted([(tid, len(entries) / total_app)
                              for tid, entries in team_data.items()],
                             key=lambda x: -x[1])
        top1_tid, top1_share = team_shares[0]
        top2_tid, _ = team_shares[1] if len(team_shares) > 1 else (None, 0)
        top3_tid, _ = team_shares[2] if len(team_shares) > 2 else (None, 0)
        top3_share = sum(s for _, s in team_shares[:3])
        hhi_all = sum(s ** 2 for _, s in team_shares)
        effective_n = 1 / hhi_all if hhi_all > 0 else float("nan")
        n_gt_5pct = sum(1 for _, s in team_shares if s > 0.05)

        # Top1 team's top-10% contribution (Codex R33 sanity check)
        top1_entries = team_data[top1_tid]
        top1_top10_count = sum(1 for ep, _ in top1_entries if ep >= 0.90)
        top1_top10_rate = top1_top10_count / len(top1_entries) if top1_entries else 0

        # Full metrics
        full_metrics = compute_country_metrics_from_appearances(team_data)
        full_top10_rate = full_metrics["top10_share"]
        full_perf_pct = float(country_row["performance_composite_pct"])
        full_div_perf = float(country_row.get("divergence_performance", "nan"))

        row = {
            "iso2": country,
            "country": {"UA": "Ukraine", "AR": "Argentina", "CZ": "Czechia",
                        "MY": "Malaysia", "SA": "Saudi Arabia", "TH": "Thailand"}[country],
            "source": source,
            "vintage_year": vintage,
            "pattern": OUTLIERS[country],
            "inclusion_tier": country_row["inclusion_tier"],
            "n_unique_teams": n_unique,
            "total_appearances": total_app,
            "top1_team_id": top1_tid,
            "top1_team_name": team_names.get(top1_tid, "")[:40],
            "top1_appearances": len(team_data[top1_tid]),
            "top1_share": round(top1_share, 4),
            "top1_top10_count": top1_top10_count,
            "top1_top10_rate": round(top1_top10_rate, 4),
            "top2_team_id": top2_tid or "",
            "top2_team_name": team_names.get(top2_tid, "")[:40] if top2_tid else "",
            "top3_team_id": top3_tid or "",
            "top3_team_name": team_names.get(top3_tid, "")[:40] if top3_tid else "",
            "top3_share": round(top3_share, 4),
            "hhi_all_teams": round(hhi_all, 4),
            "effective_team_count": round(effective_n, 2),
            "n_teams_gt_5pct": n_gt_5pct,
            "top10_rate_full": round(full_top10_rate, 4),
            "performance_composite_pct_full": round(full_perf_pct, 2),
            "divergence_performance_full": round(full_div_perf, 2),
        }

        # After-removal columns only for positive outliers
        if OUTLIERS[country] == "positive":
            # Remove top-1
            td_minus1 = remove_top_n_teams(team_data, 1)
            if td_minus1:
                m1 = compute_country_metrics_from_appearances(td_minus1)
                new_perf1, new_div1 = country_composite_from_metrics(m1, vintage_group, country)
                row["top10_rate_minus_top1"] = round(m1["top10_share"], 4)
                row["performance_composite_pct_minus_top1"] = round(new_perf1, 2)
                row["divergence_performance_minus_top1"] = round(new_div1, 2)
                row["delta_divergence_top1"] = round(new_div1 - full_div_perf, 2)
            else:
                row["top10_rate_minus_top1"] = ""
                row["performance_composite_pct_minus_top1"] = ""
                row["divergence_performance_minus_top1"] = ""
                row["delta_divergence_top1"] = ""

            # Remove top-3 (sensitivity)
            td_minus3 = remove_top_n_teams(team_data, 3)
            if td_minus3:
                m3 = compute_country_metrics_from_appearances(td_minus3)
                new_perf3, new_div3 = country_composite_from_metrics(m3, vintage_group, country)
                row["top10_rate_minus_top3"] = round(m3["top10_share"], 4)
                row["divergence_performance_minus_top3"] = round(new_div3, 2)
            else:
                row["top10_rate_minus_top3"] = ""
                row["divergence_performance_minus_top3"] = ""
            row["notes"] = ""
        else:
            # Negative outliers: blank the removal columns (Codex R32 directive)
            for k in ["top10_rate_minus_top1", "performance_composite_pct_minus_top1",
                      "divergence_performance_minus_top1", "delta_divergence_top1",
                      "top10_rate_minus_top3", "divergence_performance_minus_top3"]:
                row[k] = ""
            row["notes"] = "Negative-divergence outlier; after-removal not reported per pre-registered analysis plan"

        out_rows.append(row)

    # Output CSV
    fields = [
        "iso2", "country", "source", "vintage_year", "pattern",
        "inclusion_tier", "n_unique_teams", "total_appearances",
        "top1_team_id", "top1_team_name", "top1_appearances", "top1_share",
        "top1_top10_count", "top1_top10_rate",
        "top2_team_id", "top2_team_name", "top3_team_id", "top3_team_name",
        "top3_share", "hhi_all_teams", "effective_team_count", "n_teams_gt_5pct",
        "top10_rate_full", "performance_composite_pct_full",
        "divergence_performance_full",
        "top10_rate_minus_top1", "performance_composite_pct_minus_top1",
        "divergence_performance_minus_top1", "delta_divergence_top1",
        "top10_rate_minus_top3", "divergence_performance_minus_top3",
        "notes",
    ]
    out_path = PA / "outlier_concentration_audit.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nWrote {out_path} ({len(out_rows)} rows)")

    # Console summary
    print("\n=== Concentration audit summary ===")
    for r in out_rows:
        if r["pattern"] == "positive":
            print(f"  {r['iso2']} {r['vintage_year']} (POS): "
                  f"n_teams={r['n_unique_teams']:>3} | top1='{r['top1_team_name'][:20]}' "
                  f"share={r['top1_share']:.1%} | HHI={r['hhi_all_teams']:.3f} | "
                  f"eff_n={r['effective_team_count']:.1f} | "
                  f"div_full={r['divergence_performance_full']:+5.1f} → "
                  f"div_-top1={r['divergence_performance_minus_top1']:+5} → "
                  f"div_-top3={r['divergence_performance_minus_top3']:+5}")
        else:
            print(f"  {r['iso2']} {r['vintage_year']} (NEG): "
                  f"n_teams={r['n_unique_teams']:>3} | top1='{r['top1_team_name'][:20]}' "
                  f"share={r['top1_share']:.1%} | HHI={r['hhi_all_teams']:.3f} | "
                  f"eff_n={r['effective_team_count']:.1f} | "
                  f"div_full={r['divergence_performance_full']:+5.1f}")


if __name__ == "__main__":
    main()
