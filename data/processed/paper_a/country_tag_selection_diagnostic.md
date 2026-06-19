# Country-tag selection diagnostic (T3 per Codex Round 12B)

**Sample**: 268,704 teams that placed in ≥1 scored event

**Country-tagged rate (placed teams)**: 10.3%

## Logistic regression: has_country ~ activity + academic + cohort

All features standardized for fit; coefficients reported on original scale. Marginal effect computed at sample mean p̄.

| Predictor | β | Marginal effect (pp) |
|---|---|---|
| log_events | +1.7555 | +16.22 |
| years_active | -0.3024 | -2.79 |
| any_top100 | +0.4111 | +3.80 |
| academic | +5.5612 | +51.38 |
| first_year | +0.0321 | +0.30 |
| intercept | -68.9355 | — |

## Country-tag rate by activity stratum

| Stratum | N | N tagged | % tagged |
|---|---|---|---|
| all placed teams | 268,704 | 27,674 | 10.3% |
| >=3 events | 43,324 | 14,675 | 33.9% |
| >=2 active years | 46,587 | 12,373 | 26.6% |
| >=5 events & >=2 years | 20,419 | 8,990 | 44.0% |
| >=1 top-100 placement | 56,768 | 12,915 | 22.8% |
| academic flag | 6,536 | 6,307 | 96.5% |
| non-academic | 262,168 | 21,367 | 8.2% |

## Implication for Paper A RQ-A1 estimand

- Among teams meeting the Codex-recommended Paper A inclusion criteria (≥5 events AND ≥2 active years), 44.0% are country-tagged.
- The country-tagged subset is selectively *more active and more elite*: log_events and any_top100 are the strongest predictors of self-tagging.
- **Recommended manuscript framing**: 'Our A1 estimand is the **country-attributed, competitively engaged segment** of the global CTFtime ecosystem. Inferences do NOT extend to single-event entrants or to platforms outside CTFtime.'
