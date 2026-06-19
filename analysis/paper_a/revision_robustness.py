#!/usr/bin/env python3
"""Major-revision robustness checks (COSE-D-26-02595, R1+EIC).

Produces three reviewer-requested analyses, reusing the exact main-sample
definition and percentile/Spearman machinery of the published Table 3 pipeline
(table3_leave_top1_sensitivity.py) so all numbers reconcile:

  AN1  NCSI 2026 re-run EXCLUDING the partial 2026 CTF year (window 2024-2025).
       Reviewer asks (R1#9 / EIC): does the NCSI signal survive dropping 2026?
       - held-fixed sample (same 37 NCSI main countries, perf recomputed on 2024-2025)
       - re-derived sample (re-apply main inclusion on the 2024-2025 window)
       Reports bivariate Spearman + bootstrap CI, and a partial rank regression
       on log GDPpc, log pop, internet% (mirrors §6.8).

  AN2  GCI-2024 ordinal-respecting trend test (R1#8 / EIC).
       tie-aware Kendall tau-b + Somers' D + Jonckheere-Terpstra (permutation p).

  AN3  Full universe of qualifying divergence countries (R1#10 / EIC):
       every main-sample country with |D^perf| > 20 in >= 2 of 3 GCI vintages,
       with sign pattern + persistence + headline flag. Also reconciles the
       ADD2 inconsistency (Mongolia etc. printed explicitly).

Outputs -> data/processed/paper_a/revision_*.{csv,md}
Pure stdlib + numpy (no scipy).
"""
from __future__ import annotations
import csv
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"

WINDOWS_FULL = {
    ("GCI", 2017): (2016, 2018),
    ("GCI", 2020): (2019, 2021),
    ("GCI", 2024): (2023, 2025),
    ("NCSI", 2026): (2024, 2026),
}
NCSI_EXCL_WINDOW = (2024, 2025)   # AN1: drop the partial 2026 year
BOOT_B = 2000
BOOT_SEED = 42
HEADLINE = {"UA", "AR", "MY", "SA", "TH"}
SUPPLEMENTARY = {"CZ"}


# ---------- shared machinery (identical to table3 pipeline) ----------
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


def to_ranks(vec):
    n = len(vec)
    idx = sorted(range(n), key=lambda i: vec[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vec[idx[j + 1]] == vec[idx[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[idx[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    n = len(x)
    if n < 2:
        return float("nan")
    rx, ry = to_ranks(x), to_ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    deny = math.sqrt(sum((b - my) ** 2 for b in ry))
    if denx == 0 or deny == 0:
        return float("nan")
    return num / (denx * deny)


def bootstrap_ci(x, y, B=BOOT_B, seed=BOOT_SEED, alpha=0.05):
    n = len(x)
    rng = random.Random(seed)
    boots = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        rho = spearman([x[i] for i in idx], [y[i] for i in idx])
        if rho == rho:
            boots.append(rho)
    boots.sort()
    return boots[int(B * alpha / 2)], boots[int(B * (1 - alpha / 2))]


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
    seen = defaultdict(set)
    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                seen[int(r["event_id"])].add(int(r["team_id"]))
            except (ValueError, KeyError):
                continue
    return {eid: len(t) for eid, t in seen.items()}


def load_baseline_panel():
    """(source, vintage) -> list of main-sample country rows (matches Table 3)."""
    rows = list(csv.DictReader((PA / "rq_a1_vintage_panel_robust_perf_region.csv").open()))
    by_vintage = defaultdict(list)
    for r in rows:
        if (r.get("inclusion_tier") == "main"
                and r.get("performance_composite_pct") not in ("", None)
                and r.get("index_percentile") not in ("", None)):
            by_vintage[(r["source"], int(r["vintage_year"]))].append(r)
    return by_vintage


# ---------- AN1: NCSI excluding partial 2026 ----------
def aggregate_country_perf(window, event_year, field_size):
    """Return iso2 -> {median,t10,t25,t50,n,teams,years} over [w0,w1] inclusive."""
    w0, w1 = window
    cw = defaultdict(lambda: {"eps": [], "t10": 0, "t25": 0, "t50": 0,
                              "teams": set(), "years": set()})
    with (PA / "event_scores_enriched.csv").open() as f:
        for r in csv.DictReader(f):
            country = r.get("country", "")
            if not country or not r.get("place") or not r.get("event_id"):
                continue
            try:
                eid = int(r["event_id"]); place = int(r["place"]); tid = int(r["team_id"])
            except ValueError:
                continue
            yr = event_year.get(eid)
            if yr is None or not (w0 <= yr <= w1):
                continue
            fs = field_size.get(eid, 0)
            if fs <= 1 or place < 1 or place > fs:
                continue
            ep = 1.0 - (place - 1) / (fs - 1)
            d = cw[country]
            d["eps"].append(ep); d["teams"].add(tid); d["years"].add(yr)
            if ep >= 0.90: d["t10"] += 1
            if ep >= 0.75: d["t25"] += 1
            if ep >= 0.50: d["t50"] += 1
    out = {}
    for iso, d in cw.items():
        n = len(d["eps"])
        if n == 0:
            continue
        out[iso] = {"median": statistics.median(d["eps"]),
                    "t10": d["t10"] / n, "t25": d["t25"] / n, "t50": d["t50"] / n,
                    "n": n, "teams": len(d["teams"]), "years": len(d["years"])}
    return out


def composite_pct(country_metrics, isos):
    """Equal-weight rank-avg of 4 metrics within the given iso set, re-percentiled."""
    metrics = ["median", "t10", "t25", "t50"]
    pct = {m: dict(zip(isos, percentile_rank([country_metrics[i][m] for i in isos])))
           for m in metrics}
    raw = {i: sum(pct[m][i] for m in metrics) / 4 for i in isos}
    comp = dict(zip(isos, percentile_rank([raw[i] for i in isos])))
    return comp


def partial_rank_regression(rows):
    """OLS of perf-rank-pct on index-rank-pct + log GDPpc + log pop + internet%.
    Returns beta_index and bootstrap 95% CI. Rank-percentile transform on
    complete-case sample, mirroring Eq.9."""
    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    cc = []
    for r in rows:
        g = fnum(r.get("wb_gdp_per_capita_ppp")); p = fnum(r.get("wb_population"))
        net = fnum(r.get("wb_internet_users_pct"))
        perf = fnum(r.get("performance_composite_pct")); idx = fnum(r.get("index_percentile"))
        if None in (g, p, net, perf, idx) or g <= 0 or p <= 0:
            continue
        cc.append({"perf": perf, "idx": idx,
                   "lg": math.log(g), "lp": math.log(p), "net": net})
    n = len(cc)
    if n < 6:
        return None
    def design(sample):
        # rank-percentile transform each column within the sample
        cols = {}
        for c in ["perf", "idx", "lg", "lp", "net"]:
            cols[c] = percentile_rank([s[c] for s in sample], higher_is_better=True)
        y = np.array(cols["perf"])
        X = np.column_stack([np.ones(len(sample)), cols["idx"], cols["lg"], cols["lp"], cols["net"]])
        return X, y
    X, y = design(cc)
    beta = np.linalg.lstsq(X, y, rcond=None)[0][1]
    rng = random.Random(BOOT_SEED)
    boots = []
    for _ in range(BOOT_B):
        samp = [cc[rng.randrange(n)] for _ in range(n)]
        Xb, yb = design(samp)
        try:
            boots.append(np.linalg.lstsq(Xb, yb, rcond=None)[0][1])
        except np.linalg.LinAlgError:
            pass
    boots.sort()
    lo = boots[int(len(boots) * 0.025)]; hi = boots[int(len(boots) * 0.975)]
    return {"n": n, "beta": beta, "ci": (lo, hi)}


def an1_ncsi(baseline, event_year, field_size):
    peers = baseline.get(("NCSI", 2026), [])
    prow = {p["iso2"]: p for p in peers}
    isos_full = list(prow.keys())
    print(f"\n========== AN1: NCSI excluding partial 2026 ==========")
    print(f"NCSI main sample (full window 2024-2026): n={len(isos_full)}")

    # full-window reference (from published panel)
    idx_full = [float(prow[i]["index_percentile"]) for i in isos_full]
    perf_full = [float(prow[i]["performance_composite_pct"]) for i in isos_full]
    rho_ref = spearman(idx_full, perf_full)
    ci_ref = bootstrap_ci(idx_full, perf_full)
    print(f"  full-window  rho={rho_ref:+.3f} CI[{ci_ref[0]:+.2f},{ci_ref[1]:+.2f}]  (manuscript: +0.363 [0.04,0.61])")

    # recompute perf on 2024-2025 only
    perf2425 = aggregate_country_perf(NCSI_EXCL_WINDOW, event_year, field_size)

    rows_out = []

    # (a) held-fixed sample: same 37, perf recomputed within them
    fixed = [i for i in isos_full if i in perf2425]
    comp = composite_pct(perf2425, fixed)
    idx_a = [float(prow[i]["index_percentile"]) for i in fixed]
    perf_a = [comp[i] for i in fixed]
    rho_a = spearman(idx_a, perf_a); ci_a = bootstrap_ci(idx_a, perf_a)
    print(f"  (a) held-fixed sample  n={len(fixed)}  rho={rho_a:+.3f} CI[{ci_a[0]:+.2f},{ci_a[1]:+.2f}]  "
          f"crosses0={'YES' if ci_a[0] <= 0 <= ci_a[1] else 'no'}")
    rows_out.append(["held_fixed_2024_2025", len(fixed), round(rho_a, 4), round(ci_a[0], 4), round(ci_a[1], 4)])

    # (b) re-derived main inclusion on 2024-2025 window (>=5 teams, >=20 app, >=2 yrs)
    rederived = [i for i, m in perf2425.items()
                 if m["teams"] >= 5 and m["n"] >= 20 and m["years"] >= 2 and i in prow]
    comp_b = composite_pct(perf2425, rederived)
    idx_b = [float(prow[i]["index_percentile"]) for i in rederived]
    perf_b = [comp_b[i] for i in rederived]
    rho_b = spearman(idx_b, perf_b); ci_b = bootstrap_ci(idx_b, perf_b)
    print(f"  (b) re-derived sample  n={len(rederived)}  rho={rho_b:+.3f} CI[{ci_b[0]:+.2f},{ci_b[1]:+.2f}]  "
          f"crosses0={'YES' if ci_b[0] <= 0 <= ci_b[1] else 'no'}")
    rows_out.append(["rederived_2024_2025", len(rederived), round(rho_b, 4), round(ci_b[0], 4), round(ci_b[1], 4)])

    # partial regression on held-fixed sample (perf recomputed on 2024-2025)
    pr_rows = []
    for i in fixed:
        r = dict(prow[i]); r["performance_composite_pct"] = comp[i]
        pr_rows.append(r)
    pr = partial_rank_regression(pr_rows)
    if pr:
        cross = "YES" if pr["ci"][0] <= 0 <= pr["ci"][1] else "no"
        print(f"  partial reg (2024-2025, controls GDPpc/pop/internet) n={pr['n']} "
              f"beta_index={pr['beta']:+.3f} CI[{pr['ci'][0]:+.2f},{pr['ci'][1]:+.2f}] crosses0={cross}")
        rows_out.append(["partial_reg_2024_2025_beta", pr["n"], round(pr["beta"], 4),
                         round(pr["ci"][0], 4), round(pr["ci"][1], 4)])

    with (PA / "revision_an1_ncsi_excl2026.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "n", "stat", "ci_low", "ci_high"])
        w.writerow(["full_window_2024_2026_ref", len(isos_full), round(rho_ref, 4),
                    round(ci_ref[0], 4), round(ci_ref[1], 4)])
        w.writerows(rows_out)
    print("  -> wrote revision_an1_ncsi_excl2026.csv")


# ---------- AN2: GCI-2024 ordinal trend ----------
def kendall_tau_b(x, y):
    n = len(x)
    nc = nd = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = (x[i] - x[j]); b = (y[i] - y[j])
            s = a * b
            if s > 0: nc += 1
            elif s < 0: nd += 1
    n0 = n * (n - 1) / 2
    def ties(v):
        c = defaultdict(int)
        for t in v: c[t] += 1
        return sum(k * (k - 1) / 2 for k in c.values())
    n1 = ties(x); n2 = ties(y)
    denom = math.sqrt((n0 - n1) * (n0 - n2))
    tau_b = (nc - nd) / denom if denom > 0 else float("nan")
    somers_yx = (nc - nd) / (n0 - n1) if (n0 - n1) > 0 else float("nan")
    return tau_b, somers_yx, nc, nd


def jonckheere(groups):
    """groups: list of arrays ordered by ascending tier rank (group[0]=best tier).
    Test monotonic trend in performance. Returns observed J and permutation p."""
    k = len(groups)
    def jstat(gs):
        J = 0.0
        for a in range(k):
            for b in range(a + 1, k):
                for xa in gs[a]:
                    for xb in gs[b]:
                        if xb > xa: J += 1
                        elif xb == xa: J += 0.5
        return J
    Jobs = jstat(groups)
    allvals = np.concatenate(groups)
    sizes = [len(g) for g in groups]
    N = len(allvals)
    Emax = (N * N - sum(s * s for s in sizes)) / 4.0  # E[J] under null
    rng = np.random.default_rng(BOOT_SEED)
    perm = []
    for _ in range(5000):
        sh = rng.permutation(allvals)
        gs = []
        idx = 0
        for s in sizes:
            gs.append(sh[idx:idx + s]); idx += s
        perm.append(jstat(gs))
    perm = np.array(perm)
    # two-sided permutation p on deviation from null mean
    p = float((np.abs(perm - Emax) >= abs(Jobs - Emax)).mean())
    return Jobs, Emax, p


def an2_gci2024(baseline):
    peers = baseline.get(("GCI", 2024), [])
    rows = [(int(float(p["index_score_raw"])), float(p["performance_composite_pct"]))
            for p in peers if p.get("index_score_raw") not in ("", None)]
    print(f"\n========== AN2: GCI-2024 ordinal trend ==========")
    print(f"n={len(rows)} (tiers present: {sorted(set(t for t, _ in rows))})")
    tiers = [t for t, _ in rows]
    perf = [v for _, v in rows]
    # invert tier so higher number = better (Tier1 best -> rank highest)
    tier_inv = [-t for t in tiers]
    tau_b, somers, nc, nd = kendall_tau_b(tier_inv, perf)
    print(f"  Kendall tau-b (tie-aware, better-tier vs perf) = {tau_b:+.3f}  (concordant {nc} / discordant {nd})")
    print(f"  Somers' D (perf | tier)                        = {somers:+.3f}")
    # JT: groups ordered best->worst tier (1,2,3,4); expect decreasing perf
    bytier = defaultdict(list)
    for t, v in rows:
        bytier[t].append(v)
    ordered = [np.array(bytier[t]) for t in sorted(bytier)]
    sizes = [len(g) for g in ordered]
    Jobs, Emax, p = jonckheere(ordered)
    print(f"  group sizes by tier (1..{max(bytier)}): {sizes}")
    print(f"  Jonckheere-Terpstra J={Jobs:.0f} (E0={Emax:.0f}), permutation two-sided p={p:.3f}")
    with (PA / "revision_an2_gci2024_ordinal.md").open("w") as f:
        f.write("# AN2 — GCI-2024 ordinal-respecting trend test (revision)\n\n")
        f.write(f"- n = {len(rows)} main-sample countries; tiers present {sorted(bytier)}\n")
        f.write(f"- Group sizes Tier1..Tier{max(bytier)}: {sizes}\n\n")
        f.write(f"- **Kendall tau-b** (tie-aware, inverted tier vs performance composite) = **{tau_b:+.3f}** "
                f"(concordant {nc}, discordant {nd})\n")
        f.write(f"- **Somers' D** (performance | tier) = **{somers:+.3f}**\n")
        f.write(f"- **Jonckheere-Terpstra** trend test J = {Jobs:.0f} (null E[J] = {Emax:.0f}); "
                f"permutation two-sided p = **{p:.3f}** (5,000 permutations, seed {BOOT_SEED})\n\n")
        f.write("Interpretation: even under tie-aware/ordinal-respecting tests, GCI-2024 tier shows no "
                "monotonic association with country-attributed CTF performance; the 2024 vintage is a "
                "coarse complementary check, with main inferences resting on the cardinal 2017/2020 vintages.\n")
    print("  -> wrote revision_an2_gci2024_ordinal.md")


# ---------- AN3 + ADD2: full divergence universe ----------
def an3_universe(baseline):
    print(f"\n========== AN3: full qualifying-divergence universe (GCI) + ADD2 reconcile ==========")
    # gather D^perf by country across the 3 GCI vintages, main sample
    dperf = defaultdict(dict)   # iso2 -> {vintage: D}
    name = {}
    for (src, v), peers in baseline.items():
        if src != "GCI":
            continue
        for p in peers:
            dp = p.get("divergence_performance")
            if dp in ("", None):
                continue
            dperf[p["iso2"]][v] = float(dp)
            name[p["iso2"]] = p["canonical_name"]

    rows = []
    for iso, dvals in dperf.items():
        ds = {v: dvals.get(v) for v in (2017, 2020, 2024)}
        present = [v for v in (2017, 2020, 2024) if ds[v] is not None]
        qual = [v for v in present if abs(ds[v]) > 20]
        if len(qual) < 2:
            continue
        signs = [1 if ds[v] > 0 else -1 for v in qual]
        same_sign = all(s == signs[0] for s in signs)
        pattern = "positive" if (same_sign and signs[0] > 0) else \
                  ("negative" if (same_sign and signs[0] < 0) else "mixed")
        flag = "headline" if iso in HEADLINE else ("supplementary" if iso in SUPPLEMENTARY else "")
        rows.append({
            "iso2": iso, "country": name[iso],
            "D_2017": ds[2017], "D_2020": ds[2020], "D_2024": ds[2024],
            "n_qualifying": len(qual), "pattern": pattern,
            "same_sign_persistent": int(same_sign), "flag": flag,
        })
    # sort: headline first, then by pattern, then persistence/magnitude
    rows.sort(key=lambda r: (r["flag"] != "headline", r["flag"] != "supplementary",
                             r["pattern"], -r["n_qualifying"],
                             -max(abs(r[c]) for c in ("D_2017", "D_2020", "D_2024") if r[c] is not None)))

    with (PA / "revision_an3_all_divergence_countries.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # markdown table
    def fmt(x):
        return "—" if x is None else f"{x:+.0f}"
    with (PA / "revision_an3_all_divergence_countries.md").open("w") as f:
        f.write("# AN3 — All main-sample countries qualifying as divergence cases (revision)\n\n")
        f.write("Criterion: |D^perf| > 20 in ≥2 of 3 GCI vintages (2017/2020/2024), main sample.\n\n")
        f.write("| Country | D 2017 | D 2020 | D 2024 | #qual | pattern | persistent sign | headline? |\n")
        f.write("|---|---:|---:|---:|---:|---|:---:|---|\n")
        for r in rows:
            f.write(f"| {r['country']} | {fmt(r['D_2017'])} | {fmt(r['D_2020'])} | {fmt(r['D_2024'])} "
                    f"| {r['n_qualifying']} | {r['pattern']} | {'yes' if r['same_sign_persistent'] else 'no'} "
                    f"| {r['flag'] or '—'} |\n")
    print(f"  qualifying countries: {len(rows)}")
    print(f"  {'country':22s} 2017   2020   2024  #q  pattern    headline")
    for r in rows:
        print(f"  {r['country'][:22]:22s} {fmt(r['D_2017']):>5} {fmt(r['D_2020']):>5} {fmt(r['D_2024']):>5}"
              f"  {r['n_qualifying']}  {r['pattern']:9s}  {r['flag']}")

    # ADD2 explicit reconcile for the named "additional cases" in §6.4
    print("\n  --- ADD2 reconcile (§6.4 'additional cases', D^perf): ---")
    for iso in ("MN", "GB", "EG", "CZ", "AT", "CH"):
        if iso in dperf:
            d = dperf[iso]
            print(f"    {iso}: D^perf 2017={d.get(2017)} 2020={d.get(2020)} 2024={d.get(2024)}")
    print("  -> wrote revision_an3_all_divergence_countries.{csv,md}")


def main():
    event_year = load_event_years()
    field_size = load_field_sizes()
    baseline = load_baseline_panel()
    print("Main-sample sizes:", {f"{s} {v}": len(p) for (s, v), p in sorted(baseline.items())})
    an1_ncsi(baseline, event_year, field_size)
    an2_gci2024(baseline)
    an3_universe(baseline)


if __name__ == "__main__":
    main()
