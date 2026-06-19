# GCI 2024 ordinal-tier analysis (per Codex Round 15 robustness #5)

GCI 2024 (v5) is tier-categorical (1-5), unlike GCI 2017/2020 which are cardinal. To avoid imputing artificial precision, we compare performance composite distributions across tiers using ordinal-aware analysis.

## Performance composite percentile by GCI 2024 tier

| Tier | N | Mean perf% | Median | Std |
|---|---|---|---|---|
| 1 | 26 | 58.75 | 65.52 | 27.10 |
| 2 | 10 | 67.93 | 63.80 | 22.45 |
| 3 | 5 | 36.90 | 24.14 | 30.05 |
| 4 | 1 | 51.72 | 51.72 | 0.00 |

**Monotonicity (Tier 1 best → Tier 5 worst)**: NO

## Kendall's τ (ordinal-aware): tier × performance

- τ = **+0.057**  (95% bootstrap CI: [-0.138, +0.240])
- N = 42 country observations

## Methods note

The 2024 vintage uses a 5-tier categorical assignment introduced in GCI v5 (ITU 2024). Many countries within a tier share identical positions in the index, which compresses the discriminating power of correlation analysis. We report:
1. Within-vintage **percentile rank** (with mid-rank tied positions) for cross-vintage comparability;
2. **Kendall's τ** on the original tier ordinal, which is invariant to tie compression;
3. Distributional summaries of CTF performance composite per tier (table above).

Findings should be interpreted accordingly: 2024 results carry lower discriminating resolution than 2017/2020 cardinal scores.
