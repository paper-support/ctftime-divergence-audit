#!/usr/bin/env python3
"""V5 P2.4 — V_cv weighting sensitivity (Paruolo/Munda).

Recompute V_cv using:
  (a) Arithmetic mean (default; current paper)
  (b) Geometric mean (Munda's non-compensatory variant)
  (c) Paruolo-style "effective weight" estimate (correlation of each metric's
      rank-percentile contribution with V_cv across countries)

Compare country rankings between (a) and (b). Output a summary indicating
whether top divergence outliers are stable across weighting choices.
"""
import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"

WINDOWS = [
    ("GCI", 2017),
    ("GCI", 2020),
    ("GCI", 2024),
    ("NCSI", 2026),
]


def spearman(x, y):
    n = len(x)
    if n < 2:
        return float("nan")
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
            pct[indexed[k][0]] = round(p, 4)
        i = j + 1
    return pct


def main():
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf_region.csv").open()))
    out_rows = []

    for source, vintage in WINDOWS:
        peers = [r for r in rows
                 if r["source"] == source
                 and int(r["vintage_year"]) == vintage
                 and r["inclusion_tier"] == "main"
                 and r["index_percentile"] not in ("", None)]
        if not peers:
            continue

        # 4 metric within-vintage percentile arrays (already in panel)
        m_keys = ["median_event_percentile_pct", "top10_pct_share_pct",
                  "top25_pct_share_pct", "top50_pct_share_pct"]

        # Arithmetic V_cv (matches existing paper)
        v_arith = [sum(float(r[k]) for k in m_keys) / 4 for r in peers]

        # Geometric V_cv (Munda non-compensatory). Add small epsilon to avoid log(0).
        eps = 1e-3
        def gmean(vals):
            return math.exp(sum(math.log(max(v, eps)) for v in vals) / len(vals))
        v_geom = [gmean([float(r[k]) for k in m_keys]) for r in peers]

        # Paruolo-style empirical weights:
        # For each metric, compute its Pearson-like correlation with V_arith;
        # express as proportion of total |corr| → effective weight estimate.
        def pearson(x, y):
            n = len(x)
            mx, my = sum(x)/n, sum(y)/n
            num = sum((a-mx)*(b-my) for a, b in zip(x, y))
            dx = math.sqrt(sum((a-mx)**2 for a in x))
            dy = math.sqrt(sum((b-my)**2 for b in y))
            return num / (dx * dy) if dx and dy else float("nan")

        m_corrs = []
        for k in m_keys:
            kvals = [float(r[k]) for r in peers]
            m_corrs.append(abs(pearson(kvals, v_arith)))
        total = sum(m_corrs)
        eff_weights = [c / total for c in m_corrs] if total > 0 else [0.25] * 4

        # Compare country rankings: arithmetic vs geometric
        # Re-rank both to within-vintage percentiles
        rank_a = percentile_rank(v_arith)
        rank_g = percentile_rank(v_geom)
        rho_ag = spearman(rank_a, rank_g)

        # Top-5 outliers stability check
        idx_pct = [float(r["index_percentile"]) for r in peers]
        div_a = [a - i for a, i in zip(rank_a, idx_pct)]
        div_g = [g - i for g, i in zip(rank_g, idx_pct)]

        # Identify top-5 positive and top-5 negative under arithmetic
        pairs_a = sorted([(peers[k]["canonical_name"], div_a[k]) for k in range(len(peers))],
                         key=lambda x: -x[1])
        top_pos = pairs_a[:5]
        top_neg = pairs_a[-5:]

        # Their divergence under geometric
        for_geom = {peers[k]["canonical_name"]: div_g[k] for k in range(len(peers))}
        pos_stability = [(n, d_a, for_geom[n], for_geom[n] - d_a) for n, d_a in top_pos]
        neg_stability = [(n, d_a, for_geom[n], for_geom[n] - d_a) for n, d_a in top_neg]

        print(f"\n=== {source} {vintage} (n={len(peers)}) ===")
        print(f"  Arithmetic ↔ Geometric Spearman ρ = {rho_ag:.4f}")
        print(f"  Effective weights (Paruolo-style): "
              f"median={eff_weights[0]:.3f}, top10={eff_weights[1]:.3f}, "
              f"top25={eff_weights[2]:.3f}, top50={eff_weights[3]:.3f}")
        print(f"  Top-5 positive divergence (arith) stability:")
        for n, d_a, d_g, delta in pos_stability:
            print(f"    {n:<25}  arith={d_a:+.1f}  geom={d_g:+.1f}  Δ={delta:+.1f}")
        print(f"  Top-5 negative divergence (arith) stability:")
        for n, d_a, d_g, delta in neg_stability:
            print(f"    {n:<25}  arith={d_a:+.1f}  geom={d_g:+.1f}  Δ={delta:+.1f}")

        out_rows.append({
            "source": source,
            "vintage_year": vintage,
            "n": len(peers),
            "rho_arith_geom_v_pct": round(rho_ag, 4),
            "eff_weight_median": round(eff_weights[0], 4),
            "eff_weight_top10": round(eff_weights[1], 4),
            "eff_weight_top25": round(eff_weights[2], 4),
            "eff_weight_top50": round(eff_weights[3], 4),
        })

    out_path = PA / "v_cv_weighting_sensitivity.csv"
    with out_path.open("w") as f:
        if out_rows:
            wr = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            wr.writeheader()
            for r in out_rows:
                wr.writerow(r)
    print(f"\n✅ Written → {out_path}")


if __name__ == "__main__":
    main()
