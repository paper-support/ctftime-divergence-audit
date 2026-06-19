# Phase 0.5 Gate-Check Report
Generated post Codex round 7. Source: data/raw/validation/.

| ID | Tier | Status | Value | Threshold | Name |
|---|---|---|---|---|---|
| G1 | hard | **SKIP** | — | ≥98% | /results/ ↔ /stats/ annual ranking agreement |
| G2 | hard | **PEND** | event_tasks fetched: 0 | ≥95% | event_tasks task-ID coverage vs writeup index |
| G3 | hard | **PASS** | 197/200 = 98.5% | ≥80% | writeup plain-text usable rate |
| G4 | hard | **PEND** | queue 30 random writeups for manual review | <5% FP | English-detection false-positive rate (manual) |
| G5 | scope | **SCOPE-DOWNGRADE** | 4/50 = 8.0% | ≥30% | tier-2 academic evidence yield |
| G6 | hard | **PASS** | mismatch 0/100 = 0.0% (ambiguous 41, matched 59) | <10% | country mismatch / migration ambiguity rate |
| G7 | scope | **SCOPE-OMIT** | 19/90 = 21.1%; mean votes/populated event ≈ 17.9 | ≥60% main / 30-60% appendix / <30% omit | historical /event/{id}/weight populated rate |

## Notes

### G1 — /results/ ↔ /stats/ annual ranking agreement

Awaiting /stats/{year}/ parser fix (deferred from round 7).

### G2 — event_tasks task-ID coverage vs writeup index

HTML chain still in events stage; event_tasks not yet collected.

### G3 — writeup plain-text usable rate

flagged short(<200ch): 0; flagged non-EN: 3; non-EN samples: [('40687.html', 0.8003322259136213, 0.04905660377358491, 3010), ('40705.html', 0.5825112107623318, 0.03888888888888889, 4460), ('40756.html', 0.673974540311174, 0.05982905982905983, 1414)]

### G4 — English-detection false-positive rate (manual)

Manual review queue should be added in next iteration.

### G5 — tier-2 academic evidence yield

sample yes: ['academic-1679.html', 'academic-22109.html', 'academic-25932.html']; below threshold means tier-2/3 evidence NOT used as model features (per Codex round 5).

### G6 — country mismatch / migration ambiguity rate

sample mismatches: []

### G7 — historical /event/{id}/weight populated rate

empty samples: ['2012-10-weight.html', '2012-11-weight.html', '2012-14-weight.html', '2012-16-weight.html', '2012-17-weight.html']; votes parsed via JS-array regex (`data.addRows([['user',w],…])`)

