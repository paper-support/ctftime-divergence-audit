#!/usr/bin/env python3
"""Fetch missing ITU GCI PDFs via configured proxy.

Usage:
  python data_collection/fetch_missing_gci.py

Writes attempt logs to data/raw/external/gci/*-fetch-attempts.json and saves
successful PDFs as gci-2024.pdf or gci-2018-full.pdf.
"""
from __future__ import annotations
from pathlib import Path
import datetime as dt, hashlib, json
import httpx

PROXY = "http://127.0.0.1:7897"
OUT = Path("data/raw/external/gci"); OUT.mkdir(parents=True, exist_ok=True)
HEADERS = {
    "User-Agent": "ctftime-research-academic/0.1 (external-data fetch; contact: h@alum.vassar.edu)",
    "Accept": "application/pdf,text/html,*/*",
}

TARGETS = {
    "gci-2024": [
        "https://www.itu.int/dms_pub/itu-d/opb/hdb/d-hdb-gci.01-2024-pdf-e.pdf",
        "https://www.itu.int/en/ITU-D/Cybersecurity/Documents/GCIv5/2401416_1b_Global-Cybersecurity-Index-E.pdf",
        "https://eksec.net/wp-content/uploads/2024/09/ITUPublication-CyberSecurity-Index-2024.pdf",
        "https://repository.ca.go.ke/items/8bd09b30-164a-4cc1-ad37-528f6494168a",
        "https://repository.ca.go.ke/handle/123456789/1545",
    ],
    "gci-2018-full": [
        "https://www.itu.int/dms_pub/itu-d/opb/str/D-STR-GCI.01-2018-PDF-E.pdf",
        "https://web.archive.org/web/2019id_/https://www.itu.int/dms_pub/itu-d/opb/str/D-STR-GCI.01-2018-PDF-E.pdf",
    ],
}

def save_pdf(stem: str, url: str, resp: httpx.Response) -> bool:
    body = resp.content
    if resp.status_code not in (200, 206) or body[:4] != b"%PDF" or len(body) < 1_500_000:
        return False
    path = OUT / f"{stem}.pdf"
    path.write_bytes(body)
    meta = {
        "url": url, "final_url": str(resp.url),
        "downloaded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "byte_count": len(body), "sha256": hashlib.sha256(body).hexdigest(),
        "proxy": PROXY, "downloaded_by": "codex_script",
        "content_type": resp.headers.get("content-type", ""),
    }
    path.with_suffix(path.suffix + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("SAVED", path, len(body))
    return True

with httpx.Client(proxy=PROXY, timeout=90, follow_redirects=True, headers=HEADERS) as c:
    for stem, urls in TARGETS.items():
        log = []
        for url in urls:
            range_variants = [{}, {"Range": "bytes=1048576-"}] if "web.archive" in url else [{}]
            for extra_headers in range_variants:
                try:
                    r = c.get(url, headers=extra_headers)
                    rec = {"url": url, "range": extra_headers.get("Range"), "status": r.status_code,
                           "bytes": len(r.content), "ctype": r.headers.get("content-type", ""),
                           "content_range": r.headers.get("content-range"),
                           "sha256": hashlib.sha256(r.content).hexdigest(), "final_url": str(r.url)}
                    print(stem, rec); log.append(rec)
                    if save_pdf(stem, url, r):
                        break
                except Exception as e:
                    rec = {"url": url, "range": extra_headers.get("Range"), "error": repr(e)}
                    print(stem, rec); log.append(rec)
            if (OUT / f"{stem}.pdf").exists():
                break
        (OUT / f"{stem}-fetch-attempts.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
