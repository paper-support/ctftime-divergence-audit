#!/usr/bin/env python3
"""V5 P2.3 — NCSI 2026 leave-one-out (country jackknife) sensitivity.

Drop each main-sample country in turn, recompute Spearman ρ for NCSI 2026,
identify the most-influential country, and check whether the bivariate signal
(ρ = 0.36, CI [0.04, 0.61]) is robust to single-country influence.

Output:
  data/processed/paper_a/ncsi_jackknife.csv
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"


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


def main():
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf_region.csv").open()))
    ncsi_rows = [r for r in rows
                 if r["source"] == "NCSI"
                 and int(r["vintage_year"]) == 2026
                 and r["inclusion_tier"] == "main"
                 and r["performance_composite_pct"] not in ("", None)
                 and r["index_percentile"] not in ("", None)]
    print(f"NCSI 2026 main sample: n={len(ncsi_rows)} countries")

    iso = [r["iso2"] for r in ncsi_rows]
    name = [r["canonical_name"] for r in ncsi_rows]
    I = [float(r["index_percentile"]) for r in ncsi_rows]
    V = [float(r["performance_composite_pct"]) for r in ncsi_rows]

    rho_full = spearman(I, V)
    print(f"Full ρ = {rho_full:.4f}")

    # Jackknife — drop one country at a time
    jack = []
    for k in range(len(I)):
        Ik = [v for j, v in enumerate(I) if j != k]
        Vk = [v for j, v in enumerate(V) if j != k]
        rho_k = spearman(Ik, Vk)
        delta = rho_k - rho_full
        jack.append({
            "iso2": iso[k],
            "country": name[k],
            "rho_jackknife": round(rho_k, 4),
            "delta_rho": round(delta, 4),
        })

    # Sort by |delta_rho| descending
    jack_sorted = sorted(jack, key=lambda r: -abs(r["delta_rho"]))

    print("\nTop-5 most-influential countries (by |Δρ|):")
    for r in jack_sorted[:5]:
        print(f"  {r['country']:<25} ρ_w/o={r['rho_jackknife']:+.4f}  Δρ={r['delta_rho']:+.4f}")

    # Range of jackknife ρ
    rhos = [r["rho_jackknife"] for r in jack]
    rho_min, rho_max = min(rhos), max(rhos)
    print(f"\nJackknife ρ range: [{rho_min:.4f}, {rho_max:.4f}]  (full ρ = {rho_full:.4f})")

    # Save
    out_path = PA / "ncsi_jackknife.csv"
    with out_path.open("w") as f:
        wr = csv.DictWriter(f, fieldnames=["iso2", "country", "rho_jackknife", "delta_rho"])
        wr.writeheader()
        for r in jack_sorted:
            wr.writerow(r)
    print(f"\n✅ Written → {out_path}")

    # Also a summary line
    summary_path = PA / "ncsi_jackknife_summary.csv"
    with summary_path.open("w") as f:
        wr = csv.writer(f)
        wr.writerow(["metric", "value"])
        wr.writerow(["rho_full", round(rho_full, 4)])
        wr.writerow(["n", len(I)])
        wr.writerow(["jackknife_min_rho", round(rho_min, 4)])
        wr.writerow(["jackknife_max_rho", round(rho_max, 4)])
        wr.writerow(["max_abs_delta", round(max(abs(r["delta_rho"]) for r in jack), 4)])
        wr.writerow(["most_influential_country", jack_sorted[0]["country"]])
        wr.writerow(["most_influential_iso2", jack_sorted[0]["iso2"]])
    print(f"   → {summary_path}")


if __name__ == "__main__":
    main()
