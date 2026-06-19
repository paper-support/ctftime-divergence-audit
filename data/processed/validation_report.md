# Validation Crawl Report

Generated: 2026-05-10T10:48:36.844346+00:00

## Inventory

| stage | files | MB |
|---|---|---|
| event | 540 | 16.50 |
| team | 100 | 1.84 |
| stats | 6 | 0.25 |
| writeup | 200 | 3.52 |

## Manual checks to perform NEXT (per Codex Round 1)
- V1. Open ~10 random `team/random-*.html` and `team/academic-*.html` —
  verify country and badges are present; compare with /api/v1/teams/{id}/
  for the same teams. Note discrepancies.
- V2. Open ~10 academic-team pages — does the team profile actually look
  academic (university domain, advisor, lab page)? Estimate precision.
- V3. For 1-2 anchor years, parse `event/*-event.html` scoreboards and
  cross-check totals against /api/v1/results/{year}/ counts.
- V4. For 1-2 events from 2012/2015, verify `event/*-weight.html` returns
  vote rows (vs the API's empty historical /votes/).
- V5. Sample 20 writeups across years; assess plain-text quality, length,
  PII presence (handles/IPs/etc.), language detection.
- V6. For 1-2 events, compare `event_tasks` page against writeup-index
  task IDs — completeness check.

Findings get written into PLAN.md v3 BEFORE we launch full crawl.
