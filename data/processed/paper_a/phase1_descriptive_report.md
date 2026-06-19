# Phase 1 Descriptive Report
Generated: $(date)
Source: Phase 1 API outputs only (events, results, top, teams_index, votes). Phase 2 / HTML / writeups not used.
Per Codex round 6 prioritized items 1-11. Item 12 list lives in `paper/avoid_for_now.md`.
---
## Item 1 — Endpoint reconciliation audit
| metric | value |
|---|---|
| events table — unique IDs | 2689 |
| results table — unique event IDs | 2195 |
| events ∩ results | 2090 |
| events only | 599 |
| results only | 105 |
| score rows total | 825638 |
| registry teams | 339501 |
| distinct placed teams (any event) | 305380 |
| placed teams ∩ registry | 305228 |
| placed teams MISSING from registry | 152 |
| registry coverage of placed | 99.9502% |
| registry teams placed in ≥1 event | 305,228 (89.90%) |

**Sanity check (>98 % registry coverage of placed teams):** **PASS** (missing registry: 152)

---
## Item 2 — Activity-tail CCDF (top of distribution)
| events_per_team | n_teams | ccdf_count | ccdf_frac |
|---|---|---|---|
| 1 | 226381 | 305380 | 1.0000 |
| 2 | 32686 | 78999 | 0.2587 |
| 3 | 13215 | 46313 | 0.1517 |
| 4 | 7207 | 33098 | 0.1084 |
| 5 | 4816 | 25891 | 0.0848 |
| 6 | 3200 | 21075 | 0.0690 |
| 7 | 2409 | 17875 | 0.0585 |
| 8 | 1890 | 15466 | 0.0506 |
| 9 | 1458 | 13576 | 0.0445 |
| 10 | 1215 | 12118 | 0.0397 |
| 11 | 1044 | 10903 | 0.0357 |
| 12 | 863 | 9859 | 0.0323 |
| 13 | 740 | 8996 | 0.0295 |
| 14 | 649 | 8256 | 0.0270 |
| 15 | 521 | 7607 | 0.0249 |

Full table at `data/processed/paper_a/cohort_activity_ccdf.csv`.

---
## Item 3 — Country-tag selection diagnostic
| bucket | n_teams | n_placed | placed_frac | mean_events | mean_years | n_top100 | top100_frac | n_academic | academic_frac |
|---|---|---|---|---|---|---|---|---|---|
| country_tagged | 52647 | 28227 | 53.62% | 6.03 | 1.12 | 535 | 1.0162% | 12297 | 23.36% |
| untagged | 286854 | 277001 | 96.57% | 1.77 | 1.20 | 91 | 0.0317% | 439 | 0.15% |

---
## Item 4 — Country-year participation panel (top 20 by total active)
| country | total active-team-years (sum) |
|---|---|
| US | 7,321 |
| IN | 6,082 |
| RU | 4,180 |
| FR | 2,656 |
| CN | 2,620 |
| VN | 2,216 |
| JP | 2,101 |
| KR | 1,811 |
| DE | 1,766 |
| ID | 1,745 |
| PL | 1,285 |
| CA | 1,153 |
| GB | 1,120 |
| AU | 1,011 |
| IT | 1,005 |
| TW | 979 |
| SG | 853 |
| IR | 656 |
| NL | 640 |
| MA | 632 |

Full panel at `data/processed/paper_a/country_year_panel.csv`.

---
## Item 6 — Academic base rate by entry year
| entry_year | new_teams | academic_new | academic_frac |
|---|---|---|---|
| 2011 | 784 | 39 | 4.9745% |
| 2012 | 1667 | 26 | 1.5597% |
| 2013 | 3004 | 39 | 1.2983% |
| 2014 | 5274 | 113 | 2.1426% |
| 2015 | 6949 | 217 | 3.1228% |
| 2016 | 10188 | 297 | 2.9152% |
| 2017 | 13483 | 338 | 2.5069% |
| 2018 | 18025 | 434 | 2.4078% |
| 2019 | 33801 | 571 | 1.6893% |
| 2020 | 30549 | 692 | 2.2652% |
| 2021 | 29053 | 578 | 1.9895% |
| 2022 | 29454 | 594 | 2.0167% |
| 2023 | 30386 | 655 | 2.1556% |
| 2024 | 44110 | 781 | 1.7706% |
| 2025 | 35987 | 953 | 2.6482% |
| 2026 | 12666 | 347 | 2.7396% |

---
## Item 7 — Matching feasibility for A2
| cohort | activity | country | n_academic | n_non_academic | non_per_aca | common_support |
|---|---|---|---|---|---|---|
| early | elite | tagged | 121 | 196 | 1.6 | yes |
| early | elite | untagged | 0 | 150 | 150.0 | no |
| early | high | tagged | 127 | 535 | 4.2 | yes |
| early | high | untagged | 10 | 997 | 99.7 | yes |
| early | low | tagged | 82 | 367 | 4.5 | yes |
| early | low | untagged | 1 | 11891 | 11891.0 | no |
| early | mid | tagged | 86 | 509 | 5.9 | yes |
| early | mid | untagged | 7 | 2599 | 371.3 | yes |
| mid | elite | tagged | 185 | 370 | 2.0 | yes |
| mid | elite | untagged | 0 | 102 | 102.0 | no |
| mid | high | tagged | 530 | 1718 | 3.2 | yes |
| mid | high | untagged | 17 | 2210 | 130.0 | yes |
| mid | low | tagged | 853 | 2836 | 3.3 | yes |
| mid | low | untagged | 33 | 83114 | 2518.6 | yes |
| mid | mid | tagged | 679 | 2291 | 3.4 | yes |
| mid | mid | untagged | 35 | 11073 | 316.4 | yes |
| recent | elite | tagged | 156 | 310 | 2.0 | yes |
| recent | elite | untagged | 0 | 78 | 78.0 | no |
| recent | high | tagged | 643 | 1957 | 3.0 | yes |
| recent | high | untagged | 9 | 1697 | 188.6 | yes |
| recent | low | tagged | 1906 | 7019 | 3.7 | yes |
| recent | low | untagged | 83 | 150882 | 1817.9 | yes |
| recent | mid | tagged | 1070 | 3681 | 3.4 | yes |
| recent | mid | untagged | 41 | 12124 | 295.7 | yes |

---
## Item 9 — Event ecosystem evolution (year totals)
| year | events | mean_w | max_w | mean_part | max_part | onsite | online |
|---|---|---|---|---|---|---|---|
| 2011 | 17 | 48.82 | 100.00 | 41.6 | 267 | 7 | 10 |
| 2012 | 34 | 43.53 | 100.00 | 24.4 | 278 | 16 | 18 |
| 2013 | 55 | 33.27 | 90.00 | 29.1 | 134 | 20 | 35 |
| 2014 | 57 | 28.68 | 90.00 | 48.9 | 173 | 23 | 34 |
| 2015 | 80 | 21.93 | 90.00 | 55.1 | 182 | 32 | 48 |
| 2016 | 104 | 18.74 | 88.49 | 61.0 | 263 | 42 | 62 |
| 2017 | 132 | 19.15 | 88.49 | 67.6 | 433 | 39 | 93 |
| 2018 | 145 | 22.02 | 100.00 | 61.9 | 372 | 53 | 92 |
| 2019 | 182 | 21.19 | 100.00 | 67.2 | 541 | 52 | 130 |
| 2020 | 216 | 23.39 | 100.00 | 92.1 | 616 | 19 | 197 |
| 2021 | 233 | 24.65 | 100.00 | 76.4 | 396 | 17 | 216 |
| 2022 | 259 | 22.76 | 100.00 | 70.4 | 385 | 38 | 221 |
| 2023 | 315 | 22.96 | 100.00 | 64.2 | 507 | 68 | 247 |
| 2024 | 334 | 23.44 | 100.00 | 72.3 | 491 | 68 | 266 |
| 2025 | 340 | 24.76 | 100.00 | 76.3 | 572 | 68 | 272 |
| 2026 | 186 | 20.80 | 100.00 | 57.8 | 422 | 33 | 153 |

---
## Item 10 — AI/LLM mentions in event descriptions (Paper B context)
| year | events | with_ai_mention | frac |
|---|---|---|---|
| 2011 | 17 | 0 | 0.0000% |
| 2012 | 34 | 0 | 0.0000% |
| 2013 | 55 | 0 | 0.0000% |
| 2014 | 57 | 0 | 0.0000% |
| 2015 | 80 | 0 | 0.0000% |
| 2016 | 104 | 0 | 0.0000% |
| 2017 | 132 | 0 | 0.0000% |
| 2018 | 145 | 0 | 0.0000% |
| 2019 | 182 | 0 | 0.0000% |
| 2020 | 216 | 2 | 0.9259% |
| 2021 | 233 | 3 | 1.2876% |
| 2022 | 259 | 0 | 0.0000% |
| 2023 | 315 | 1 | 0.3175% |
| 2024 | 334 | 2 | 0.5988% |
| 2025 | 340 | 2 | 0.5882% |
| 2026 | 186 | 0 | 0.0000% |

*Reminder (Codex round 6 item 10):* If AI mentions appear in event metadata pre-2022 or are too sparse, do NOT use event descriptions for B2 — fall back to writeups only.

---
## Items 5, 8, 11 — see CSV outputs
- `worldbank_country_coverage.csv` (item 5)
- `team_year_exposure_features.csv` (item 8 — large file, use for A3 model design)
- `csrankings_country_coverage.csv` (item 11)
