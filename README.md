# CTFtime Divergence Audit

Replication code and derived data for a study auditing where national
cyber-capability indices (the ITU Global Cybersecurity Index, GCI, and the
National Cyber Security Index, NCSI) **diverge** from country-attributed
competitive performance on [CTFtime.org](https://ctftime.org) over 2011–2026.

> Associated manuscript: *"When Cybersecurity Policy Scores and Competitive CTF
> Performance Diverge: A 16-Year Audit of the GCI, NCSI, and CTFtime"*
> (under review at *Computers & Security*). Inferences apply to the
> country-attributed, academic-enriched, competitively engaged segment of
> CTFtime — not to national cyber-talent populations.

## Repository contents

```
data_collection/        Polite-crawl collectors (CTFtime API + HTML) and
                        external-index loaders (GCI, NCSI, World Bank)
analysis/paper_a/       Full analysis pipeline (see below)
analysis/paper_a/figures/   Figure-generation scripts
data/processed/paper_a/ Derived, analysis-ready tables (no raw dumps)
requirements.txt        Python dependencies
```

The analysis pipeline (`analysis/paper_a/`) covers country-name
harmonisation, the country-attribution selection model, event-percentile and
performance-composite construction, within-vintage rank transforms,
divergence scoring, within-region analysis, bootstrap / partial-rank-regression
/ jackknife robustness, the concentration (leave-top-team-out) audit, and the
revision robustness checks.

## What is NOT included (and why)

- **Raw third-party data** (ITU GCI, NCSI, World Bank): redistribution is
  subject to the original providers' terms. Obtain from source and place under
  `data/raw/`.
- **Raw CTFtime API/HTML dumps and writeup text**: not redistributed (CTFtime
  terms / author copyright). Regenerate with `data_collection/`, which respects
  CTFtime's `robots.txt` polite-crawl policy (10 s between HTML requests, 5 s
  between API requests, enforced cross-process).
- **Individual / user identifiers**: none are released. All analysis is
  conducted at the team × event × country level.

## Reproducing the analysis

```bash
python3 -m pip install -r requirements.txt
```

The derived tables in `data/processed/paper_a/` let you re-run the analysis
**without** re-crawling. Key scripts (run from the repository root):

- `analysis/paper_a/build_vintage_aligned_panel.py` — country × vintage panel
- `analysis/paper_a/build_event_percentile_panel.py` — event-percentile + performance composite
- `analysis/paper_a/recompute_divergence_robust.py` — divergence scores
- `analysis/paper_a/revision_robustness.py` — ordinal GCI-2024 test, NCSI excl-2026, full qualifying-country table
- `analysis/paper_a/all_outlier_concentration.py` — concentration / leave-top-team-out audit
- `analysis/paper_a/figures/*.py` — figures

To rebuild the derived tables from scratch, run the collectors in
`data_collection/` first (multi-day crawl).

## Licensing

- **Code** (`data_collection/`, `analysis/`): MIT — see [`LICENSE`](LICENSE).
- **Derived data** (`data/processed/paper_a/`): CC-BY-4.0.
- Raw third-party data remain under their original licences and are not
  redistributed here.

## Citation

Citation details will be added on acceptance.
