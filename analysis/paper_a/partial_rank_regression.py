#!/usr/bin/env python3
"""Partial-rank regression of CTF performance composite on policy-index rank
controlling for development variables (per Codex Round 19 risk R13, Round 42 specs).

Primary model (OLS on rank-percentile-transformed variables):

    R(V_cv) = α + β · R(I_cv) + γ_1 · log(GDP_PPP_pc)
                + γ_2 · log(population) + γ_3 · internet_users_pct + ε

For each vintage v ∈ {GCI 2017, GCI 2020, GCI 2024, NCSI 2026}, restricted to
main-sample countries (Section 4.3) with complete control data, we report:
  - n complete-case
  - β on index rank
  - Bootstrap 95% CI for β (country-resample, fixed seed, 2000 draws)
  - Residual Spearman ρ between V_cv and I_cv after residualising both on controls
  - ΔR² = R²_full - R²_controls (additional variance explained by index rank)

Sensitivity (separate column, not main table): add tertiary_education_pct.

Outputs:
  data/processed/paper_a/partial_rank_regression.csv
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data/processed/paper_a"

VINTAGES = [
    ("GCI", 2017),
    ("GCI", 2020),
    ("GCI", 2024),
    ("NCSI", 2026),
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
            pct[indexed[k][0]] = round(p, 4)
        i = j + 1
    return pct


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


def ols_fit(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """OLS fit. Returns (beta, R², residuals).
    X has shape (n, k) including the intercept column; y has shape (n,).
    """
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    residuals = y - y_hat
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return beta, r2, residuals


def safe_log(v: float) -> float | None:
    """log if v positive, else None."""
    try:
        v = float(v)
        if v <= 0:
            return None
        return math.log(v)
    except (TypeError, ValueError):
        return None


# ---------- Data loading

def load_main_sample_with_controls(vintage_source: str, vintage_year: int,
                                    include_tertiary: bool = False):
    """Returns list of dicts with iso2, index_pct, perf_pct, and log controls
    (complete-case only).
    """
    # Load worldbank controls
    wb = {}
    with (PA / "worldbank_latest_per_country.csv").open() as f:
        for r in csv.DictReader(f):
            wb[r["iso2"]] = r

    # Load main-sample panel rows for this vintage
    rows = []
    with (PA / "rq_a1_vintage_panel_robust_perf_region.csv").open() as f:
        for r in csv.DictReader(f):
            if (r["source"] == vintage_source
                    and int(r["vintage_year"]) == vintage_year
                    and r["inclusion_tier"] == "main"
                    and r.get("index_percentile") not in ("", None)
                    and r.get("performance_composite_pct") not in ("", None)):
                rows.append(r)

    out = []
    n_missing_wb = n_log_fail = 0
    for r in rows:
        iso2 = r["iso2"]
        wb_row = wb.get(iso2)
        if wb_row is None:
            n_missing_wb += 1
            continue

        gdp = safe_log(wb_row.get("gdp_per_capita_ppp"))
        pop = safe_log(wb_row.get("population"))
        try:
            internet = float(wb_row.get("internet_users_pct", ""))
        except (ValueError, TypeError):
            internet = None

        tertiary = None
        if include_tertiary:
            try:
                tertiary = float(wb_row.get("tertiary_education_pct", ""))
                if tertiary < 0 or tertiary > 200:
                    tertiary = None
            except (ValueError, TypeError):
                tertiary = None
            if tertiary is None:
                continue

        if gdp is None or pop is None or internet is None:
            n_log_fail += 1
            continue

        record = {
            "iso2": iso2,
            "index_pct": float(r["index_percentile"]),
            "perf_pct": float(r["performance_composite_pct"]),
            "log_gdp_pc": gdp,
            "log_pop": pop,
            "internet_pct": internet,
        }
        if include_tertiary:
            record["tertiary_pct"] = tertiary
        out.append(record)

    return out, n_missing_wb, n_log_fail


# ---------- Main analysis

def fit_partial_regression(records: list[dict], include_tertiary: bool = False):
    """Returns dict of {beta_index, r2_full, r2_controls, delta_r2,
                          residual_spearman, n}.
    """
    if len(records) < 5:
        return None

    n = len(records)
    # Per Codex Round 44: both LHS and RHS must be re-ranked within the same
    # complete-case (or bootstrap) sample. Original *_pct were ranked against the
    # full-vintage sample, but after complete-case filtering / bootstrap resampling
    # the relevant rank distribution is the in-sample one.
    perf_vals = [r["perf_pct"] for r in records]
    perf_ranks = np.array(percentile_rank(perf_vals, higher_is_better=True))
    y = perf_ranks

    index_vals = [r["index_pct"] for r in records]
    index_ranks = np.array(percentile_rank(index_vals, higher_is_better=True))

    # Controls: log_gdp_pc, log_pop, internet_pct (+ optional tertiary)
    log_gdp = np.array([r["log_gdp_pc"] for r in records])
    log_pop = np.array([r["log_pop"] for r in records])
    internet = np.array([r["internet_pct"] for r in records])
    cols = [log_gdp, log_pop, internet]
    col_names = ["log_gdp_pc", "log_pop", "internet_pct"]
    if include_tertiary:
        tertiary = np.array([r["tertiary_pct"] for r in records])
        cols.append(tertiary)
        col_names.append("tertiary_pct")

    # Build design matrices
    ones = np.ones(n)
    X_controls = np.column_stack([ones] + cols)
    X_full = np.column_stack([ones, index_ranks] + cols)

    # OLS — record condition number as sanity check (Codex R44 optional)
    cond_full = float(np.linalg.cond(X_full))
    beta_full, r2_full, resid_full = ols_fit(X_full, y)
    beta_ctrl, r2_ctrl, resid_ctrl = ols_fit(X_controls, y)
    beta_index = float(beta_full[1])  # coefficient on index_ranks

    # Residual Spearman: residualise both index_ranks and y on controls, then Spearman
    _, _, y_residuals = ols_fit(X_controls, y)
    _, _, idx_residuals = ols_fit(X_controls, index_ranks)
    residual_rho = spearman(idx_residuals.tolist(), y_residuals.tolist())

    return {
        "n": n,
        "beta_index": beta_index,
        "r2_full": float(r2_full),
        "r2_controls": float(r2_ctrl),
        "delta_r2": float(r2_full - r2_ctrl),
        "residual_spearman": float(residual_rho),
        "control_columns": col_names,
        "condition_number": cond_full,
    }


def bootstrap_beta_ci(records: list[dict], include_tertiary: bool = False,
                      n_boot: int = 2000, seed: int = 42,
                      ci: float = 0.95) -> tuple[float, float, float, float]:
    """Country-resample bootstrap. Returns (beta_low, beta_high, rho_low, rho_high)."""
    rng = random.Random(seed)
    n = len(records)
    if n < 5:
        return float("nan"), float("nan"), float("nan"), float("nan")

    betas = []
    rhos = []
    for _ in range(n_boot):
        idxs = [rng.randrange(n) for _ in range(n)]
        sample = [records[i] for i in idxs]
        result = fit_partial_regression(sample, include_tertiary=include_tertiary)
        if result is not None and result["beta_index"] == result["beta_index"]:
            betas.append(result["beta_index"])
            if result["residual_spearman"] == result["residual_spearman"]:
                rhos.append(result["residual_spearman"])

    betas.sort()
    rhos.sort()
    a = (1 - ci) / 2
    if not betas:
        return float("nan"), float("nan"), float("nan"), float("nan")
    bi_lo = betas[int(a * len(betas))]
    bi_hi = betas[int((1 - a) * len(betas)) - 1]
    if rhos:
        rh_lo = rhos[int(a * len(rhos))]
        rh_hi = rhos[int((1 - a) * len(rhos)) - 1]
    else:
        rh_lo = rh_hi = float("nan")
    return bi_lo, bi_hi, rh_lo, rh_hi


def main():
    print("Partial-rank regression with development controls")
    print("=" * 70)

    out_rows = []
    for source, vintage in VINTAGES:
        # Primary model
        records, n_missing_wb, n_log_fail = load_main_sample_with_controls(
            source, vintage, include_tertiary=False)
        n_total = len(records) + n_missing_wb + n_log_fail
        print(f"\n=== {source} {vintage} ===")
        print(f"  main-sample countries: {n_total}; complete-case: {len(records)} "
              f"(missing WB: {n_missing_wb}, log/internet fail: {n_log_fail})")

        result = fit_partial_regression(records, include_tertiary=False)
        if result is None:
            print(f"  Insufficient data; skipping.")
            continue

        bi_lo, bi_hi, rh_lo, rh_hi = bootstrap_beta_ci(records, include_tertiary=False)

        print(f"  Primary: n={result['n']}, β_index={result['beta_index']:+.4f} "
              f"[{bi_lo:+.4f}, {bi_hi:+.4f}]")
        print(f"           residual Spearman ρ = {result['residual_spearman']:+.4f} "
              f"[{rh_lo:+.4f}, {rh_hi:+.4f}]")
        print(f"           R²_controls = {result['r2_controls']:.4f}, "
              f"R²_full = {result['r2_full']:.4f}, "
              f"ΔR² = {result['delta_r2']:+.4f}, cond(X) = {result['condition_number']:.1f}")

        # Sensitivity: add tertiary education
        records_t, n_miss_t, n_logfail_t = load_main_sample_with_controls(
            source, vintage, include_tertiary=True)
        sens_result = fit_partial_regression(records_t, include_tertiary=True)
        if sens_result is not None:
            print(f"  Sensitivity (+ tertiary, n={sens_result['n']}): "
                  f"β_index={sens_result['beta_index']:+.4f}, "
                  f"ΔR²={sens_result['delta_r2']:+.4f}")

        out_rows.append({
            "source": source,
            "vintage_year": vintage,
            "n_complete_case": result["n"],
            "beta_index_rank": round(result["beta_index"], 4),
            "beta_ci_low": round(bi_lo, 4),
            "beta_ci_high": round(bi_hi, 4),
            "residual_spearman_rho": round(result["residual_spearman"], 4),
            "residual_spearman_ci_low": round(rh_lo, 4),
            "residual_spearman_ci_high": round(rh_hi, 4),
            "r2_controls_only": round(result["r2_controls"], 4),
            "r2_full": round(result["r2_full"], 4),
            "delta_r2": round(result["delta_r2"], 4),
            "control_columns": "|".join(result["control_columns"]),
            "condition_number": round(result["condition_number"], 2),
            "sensitivity_n": sens_result["n"] if sens_result else "",
            "sensitivity_beta_index": round(sens_result["beta_index"], 4) if sens_result else "",
            "sensitivity_delta_r2": round(sens_result["delta_r2"], 4) if sens_result else "",
            "seed": 42,
            "bootstrap_draws": 2000,
        })

    out_path = PA / "partial_rank_regression.csv"
    if out_rows:
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            w.writeheader()
            w.writerows(out_rows)
        print(f"\nWrote {out_path} ({len(out_rows)} rows)")
    else:
        print("\nNo rows to write.")


if __name__ == "__main__":
    main()
