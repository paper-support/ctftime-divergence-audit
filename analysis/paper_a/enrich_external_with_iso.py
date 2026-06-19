#!/usr/bin/env python3
"""T1 part 2 — Add iso2/iso3/percentile columns to all external CSVs.

Per Codex Round 12B: 'within-vintage percentile ranks; never mix raw cardinal scales'.

Reads:
  data/processed/paper_a/countries_canonical.csv  (from build_canonical_countries.py)
  data/raw/external/gci/gci-2017-scores.csv
  data/raw/external/gci/gci-2020-scores.csv
  data/raw/external/gci/gci-2024-tiers.csv
  data/raw/external/ncsi/ncsi-snapshot-2026.csv

Writes:
  data/processed/paper_a/external_indices_long.csv
    Long-format panel: iso2, iso3, country, source, vintage_year, score_raw,
                       percentile_rank, rank_in_vintage, n_in_vintage,
                       scale_note, is_sovereign_like

Each (iso, source, vintage) pair gets a within-vintage percentile_rank in [0, 100]
so cross-vintage joins are scale-free. Cardinal score_raw is preserved for audit
but should never be used directly in regression.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PA = ROOT / "data" / "processed" / "paper_a"
EXT = ROOT / "data" / "raw" / "external"


def _strip(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\*+\s*$", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def load_alias_to_iso() -> dict[str, tuple[str, str, str, int]]:
    """Reverse-index every source alias to (iso2, iso3, canonical_name, is_sovereign_like)."""
    out = {}
    with (PA / "countries_canonical.csv").open() as f:
        for r in csv.DictReader(f):
            iso2 = r["iso2"]
            iso3 = r["iso3"]
            name = r["canonical_name"]
            is_sov = int(r["is_sovereign_like"])
            for alias in json.loads(r["source_aliases"]):
                # alias format: "src:value"
                _, val = alias.split(":", 1)
                out[_strip(val)] = (iso2, iso3, name, is_sov)
            # also the iso2 itself maps
            out[iso2.lower()] = (iso2, iso3, name, is_sov)
            if iso3:
                out[iso3.lower()] = (iso2, iso3, name, is_sov)
            out[_strip(name)] = (iso2, iso3, name, is_sov)
    return out


def percentile_rank(scores: list[float], higher_is_better: bool = True) -> list[float]:
    """Return percentile rank (0-100) for each score. Ties get same rank.
    higher_is_better=True → top score gets 100.
    """
    n = len(scores)
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=higher_is_better)
    pct = [0.0] * n
    i = 0
    while i < n:
        # find tie group
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        # average rank in tie group (1-indexed)
        avg_rank = (i + j) / 2 + 1
        p = (1 - (avg_rank - 1) / (n - 1)) * 100 if n > 1 else 100.0
        for k in range(i, j + 1):
            orig_idx = indexed[k][0]
            pct[orig_idx] = round(p, 2)
        i = j + 1
    return pct


def main():
    alias_to_iso = load_alias_to_iso()
    print(f"Loaded {len(alias_to_iso)} alias→iso mappings")

    long_rows = []

    # ---- GCI 2017 (0-1 scale, higher = better)
    rows = list(csv.DictReader((EXT / "gci/gci-2017-scores.csv").open()))
    scores = [float(r["score"]) for r in rows]
    pcts = percentile_rank(scores, higher_is_better=True)
    for r, p in zip(rows, pcts):
        s = _strip(r["country"])
        m = alias_to_iso.get(s)
        if not m:
            print(f"  GCI2017 unresolved: {r['country']!r}")
            continue
        iso2, iso3, name, sov = m
        long_rows.append({
            "iso2": iso2, "iso3": iso3, "canonical_name": name,
            "source": "GCI", "vintage_year": 2017,
            "score_raw": r["score"], "scale_note": "0-1 cardinal",
            "rank_in_vintage": r["rank"],
            "n_in_vintage": len(rows),
            "percentile_rank": p,
            "is_sovereign_like": sov,
        })

    # ---- GCI 2020 (0-100 scale, higher = better)
    rows = list(csv.DictReader((EXT / "gci/gci-2020-scores.csv").open()))
    scores = [float(r["score"]) for r in rows]
    pcts = percentile_rank(scores, higher_is_better=True)
    for r, p in zip(rows, pcts):
        s = _strip(r["country"])
        m = alias_to_iso.get(s)
        if not m:
            print(f"  GCI2020 unresolved: {r['country']!r}")
            continue
        iso2, iso3, name, sov = m
        long_rows.append({
            "iso2": iso2, "iso3": iso3, "canonical_name": name,
            "source": "GCI", "vintage_year": 2020,
            "score_raw": r["score"], "scale_note": "0-100 cardinal",
            "rank_in_vintage": r["rank"],
            "n_in_vintage": len(rows),
            "percentile_rank": p,
            "is_sovereign_like": sov,
        })

    # ---- GCI 2024 (tier categorical, 1=best, 5=worst → invert for percentile)
    rows = list(csv.DictReader((EXT / "gci/gci-2024-tiers.csv").open()))
    # higher tier number = worse → invert
    tiers = [int(r["tier"]) for r in rows]
    pcts = percentile_rank([-t for t in tiers], higher_is_better=True)  # lower tier = higher percentile
    for r, p in zip(rows, pcts):
        s = _strip(r["country"])
        m = alias_to_iso.get(s)
        if not m:
            print(f"  GCI2024 unresolved: {r['country']!r}")
            continue
        iso2, iso3, name, sov = m
        long_rows.append({
            "iso2": iso2, "iso3": iso3, "canonical_name": name,
            "source": "GCI", "vintage_year": 2024,
            "score_raw": r["tier"], "scale_note": "tier 1-5 categorical",
            "rank_in_vintage": r["tier"],  # tier IS rank-like
            "n_in_vintage": len(rows),
            "percentile_rank": p,
            "is_sovereign_like": sov,
        })

    # ---- NCSI 2026 (0-100 cardinal, higher = better)
    rows = list(csv.DictReader((EXT / "ncsi/ncsi-snapshot-2026.csv").open()))
    scores = [float(r["score"]) for r in rows]
    pcts = percentile_rank(scores, higher_is_better=True)
    for r, p in zip(rows, pcts):
        # NCSI already has iso3 column
        iso_key = r.get("iso3", "").lower()
        m = alias_to_iso.get(iso_key) or alias_to_iso.get(_strip(r["name"]))
        if not m:
            print(f"  NCSI unresolved: {r.get('iso3')!r}/{r.get('name')!r}")
            continue
        iso2, iso3, name, sov = m
        long_rows.append({
            "iso2": iso2, "iso3": iso3, "canonical_name": name,
            "source": "NCSI", "vintage_year": 2026,
            "score_raw": r["score"], "scale_note": "0-100 cardinal",
            "rank_in_vintage": r["rank"],
            "n_in_vintage": len(rows),
            "percentile_rank": p,
            "is_sovereign_like": sov,
        })

    # ---- write long table
    out = PA / "external_indices_long.csv"
    fields = ["iso2", "iso3", "canonical_name", "source", "vintage_year",
              "score_raw", "scale_note", "rank_in_vintage", "n_in_vintage",
              "percentile_rank", "is_sovereign_like"]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(long_rows)
    print(f"\nWrote {out} ({len(long_rows)} rows)")

    # Diagnostics
    from collections import Counter
    by_source = Counter((r["source"], r["vintage_year"]) for r in long_rows)
    print(f"\nRows per (source, vintage):")
    for k, n in sorted(by_source.items()):
        print(f"  {k}: {n}")


if __name__ == "__main__":
    main()
