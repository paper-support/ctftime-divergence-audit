#!/usr/bin/env python3
"""External datasets — one-shot downloads for Paper A and Paper B.

Sources (each saved with provenance sidecar):
  - CSRankings security area CSV (machine-readable, GitHub-hosted)
  - World Bank — GDP per capita (PPP) + Internet penetration, ISO-3 country codes
  - NCSI (e-Governance Academy) — National Cyber Security Index (manual download note)
  - ITU GCI 2014/2017/2018/2020/2024 (manual download note)
  - NIST NICE Workforce Framework v2 (SP 800-181r1) — JSON + PDF (manual download note)
  - CSEC2017 (manual download note)

Manual sources are emitted as TODO entries pointing at the canonical URL — researcher
downloads the file and drops it under data/raw/external/<sub>/. This keeps provenance
clean (we never lie about an automated fetch).

Usage: python3 collect_external.py
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from utils import DATA_RAW, USER_AGENT, atomic_write_json, setup_logging

logger = setup_logging("collect_external")

# ----------------------------------------------------------------- Auto fetch

CSRANKINGS_SECURITY_RAW = (
    "https://raw.githubusercontent.com/emeryberger/CSrankings/gh-pages/csrankings.csv"
)

WORLD_BANK_INDICATORS = {
    # https://data.worldbank.org/indicator/<code>
    "gdp_per_capita_ppp": "NY.GDP.PCAP.PP.CD",
    "internet_users_pct": "IT.NET.USER.ZS",
    "tertiary_education_pct": "SE.TER.ENRR",
    "population": "SP.POP.TOTL",
}


def fetch_csrankings():
    """CSRankings is a CSV of all faculty + their institution + areas — we'll filter
    to security/crypto in the analysis stage."""
    out = DATA_RAW / "external" / "csrankings" / "csrankings.csv"
    if out.exists():
        logger.info(f"csrankings already present: {out}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    r = httpx.get(CSRANKINGS_SECURITY_RAW, timeout=60, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    out.write_bytes(r.content)
    meta = {
        "url": CSRANKINGS_SECURITY_RAW,
        "byte_count": len(r.content),
        "status": r.status_code,
    }
    out.with_suffix(".csv.meta.json").write_text(json.dumps(meta, indent=2))
    logger.info(f"csrankings: {len(r.content)} bytes -> {out}")


def fetch_world_bank():
    """World Bank API: GET /v2/country/all/indicator/{code}?format=json&date=2011:2026&per_page=20000"""
    base = "https://api.worldbank.org/v2/country/all/indicator"
    for label, code in WORLD_BANK_INDICATORS.items():
        out = DATA_RAW / "external" / "worldbank" / f"{label}.json"
        if out.exists():
            logger.info(f"world bank {label}: already present")
            continue
        url = f"{base}/{code}"
        params = {"format": "json", "date": "2011:2026", "per_page": "20000"}
        r = httpx.get(url, params=params, timeout=120, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        atomic_write_json(out, r.json(), str(r.request.url))
        logger.info(f"world bank {label}: -> {out.name}")


# ---------------------------------------------------------------- Manual TODOs

MANUAL_NOTES = """\
Manual download checklist — drop the file into the path indicated, then commit the
.meta.json sidecar (see template) so provenance is preserved.

1. ITU Global Cybersecurity Index (GCI)
   URL: https://www.itu.int/en/ITU-D/Cybersecurity/Pages/global-cybersecurity-index.aspx
   Vintages to grab: 2014, 2017, 2018, 2020, 2024 (PDF or Excel)
   Save as: data/raw/external/gci/gci-{YYYY}.pdf  (or .xlsx)

2. NCSI — National Cyber Security Index
   URL: https://ncsi.ega.ee/  → "Methodology and Data" → "Download"
   Save as: data/raw/external/ncsi/ncsi-snapshot-{YYYY-MM-DD}.csv

3. NIST NICE Workforce Framework v2 (SP 800-181r1, 2024)
   URL: https://csrc.nist.gov/Projects/NICE-Workforce-Framework
   JSON + PDF: data/raw/external/nice/nice-v2.{json,pdf}

4. CSEC2017
   URL: https://cybersecuritycurriculum.org/
   PDF: data/raw/external/nice/csec2017.pdf

After dropping each file, create a sibling .meta.json with:
  {
    "url": "<canonical source URL>",
    "downloaded_at": "<UTC ISO timestamp>",
    "byte_count": <int>,
    "sha256": "<hex>",
    "downloaded_by": "<your initials>"
  }
"""


def write_manual_notes():
    out = DATA_RAW / "external" / "MANUAL_DOWNLOADS_TODO.md"
    if out.exists():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(MANUAL_NOTES)
    logger.info(f"manual download instructions written -> {out}")


def main():
    fetch_csrankings()
    fetch_world_bank()
    write_manual_notes()
    logger.info("collect_external: done.")


if __name__ == "__main__":
    main()
