#!/usr/bin/env python3
"""Build a real World Bank country×year panel from raw JSON exports.

The previous worldbank_country_coverage.csv was a COUNT of years available,
not the actual values. This rebuilds the proper panel.

Output:
  data/processed/paper_a/worldbank_panel.csv
    iso2, iso3, country_wb_name, year, gdp_per_capita_ppp,
    internet_users_pct, population, tertiary_education_pct

  data/processed/paper_a/worldbank_latest_per_country.csv
    iso2, iso3, gdp_per_capita_ppp_latest, internet_users_pct_latest,
    population_latest, tertiary_education_pct_latest, year_used
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WB_RAW = ROOT / "data/raw/external/worldbank"
PA = ROOT / "data/processed/paper_a"


def _load_wb_indicator(name: str) -> list[dict]:
    """Returns list of {iso3, iso2_guess, country, year, value} from a WB JSON dump."""
    data = json.loads((WB_RAW / f"{name}.json").read_text())
    if not isinstance(data, list) or len(data) < 2:
        return []
    obs = data[1] if isinstance(data[1], list) else []
    out = []
    for o in obs:
        if not isinstance(o, dict):
            continue
        country = (o.get("country") or {}).get("value", "")
        iso3 = o.get("countryiso3code", "")
        year = o.get("date", "")
        value = o.get("value")
        if not iso3 or not year:
            continue
        out.append({
            "iso3": iso3,
            "country_wb_name": country,
            "year": int(year) if year.isdigit() else None,
            "value": value,
        })
    return out


def main():
    # Load canonical iso3 → iso2 lookup
    canonical = {}
    with (PA / "countries_canonical.csv").open() as f:
        for r in csv.DictReader(f):
            canonical[r["iso3"]] = {"iso2": r["iso2"], "name": r["canonical_name"]}

    # Map WB iso3 → canonical iso2 (handle XKX→XK, etc.)
    iso3_aliases = {
        "XKX": "XK",  # Kosovo
        "WBG": "PS",  # West Bank and Gaza → Palestine
        "PSE": "PS",
        "TWN": "TW",
        "HKG": "HK",
        "MAC": "MO",
    }

    indicators = {
        "gdp_per_capita_ppp": _load_wb_indicator("gdp_per_capita_ppp"),
        "internet_users_pct": _load_wb_indicator("internet_users_pct"),
        "population": _load_wb_indicator("population"),
        "tertiary_education_pct": _load_wb_indicator("tertiary_education_pct"),
    }
    for k, v in indicators.items():
        print(f"  {k}: {len(v):,} observations")

    # Build country×year panel
    panel: dict[tuple[str, int], dict] = defaultdict(dict)
    iso3_to_name = {}
    for ind, obs_list in indicators.items():
        for o in obs_list:
            iso3 = o["iso3"]
            yr = o["year"]
            if yr is None or o["value"] is None:
                continue
            # resolve to canonical iso2
            iso2 = iso3_aliases.get(iso3) or canonical.get(iso3, {}).get("iso2")
            if not iso2:
                continue
            iso3_to_name[iso3] = o["country_wb_name"]
            panel[(iso2, yr)][ind] = o["value"]
            panel[(iso2, yr)]["iso3"] = iso3
            panel[(iso2, yr)]["country_wb_name"] = o["country_wb_name"]

    # Write long-format panel
    out_panel = PA / "worldbank_panel.csv"
    rows = []
    for (iso2, year), vals in sorted(panel.items()):
        rows.append({
            "iso2": iso2,
            "iso3": vals.get("iso3", ""),
            "country_wb_name": vals.get("country_wb_name", ""),
            "year": year,
            "gdp_per_capita_ppp": vals.get("gdp_per_capita_ppp", ""),
            "internet_users_pct": vals.get("internet_users_pct", ""),
            "population": vals.get("population", ""),
            "tertiary_education_pct": vals.get("tertiary_education_pct", ""),
        })
    with out_panel.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out_panel} ({len(rows)} country-year rows)")

    # Latest available per country per indicator (forward-filled from most recent year)
    latest = defaultdict(dict)
    for r in rows:
        iso2 = r["iso2"]
        yr = r["year"]
        for ind in ["gdp_per_capita_ppp", "internet_users_pct", "population", "tertiary_education_pct"]:
            v = r[ind]
            if v != "" and v is not None:
                # keep latest year for which we have data
                if ind not in latest[iso2] or yr > latest[iso2][ind][1]:
                    latest[iso2][ind] = (v, yr)

    out_latest = PA / "worldbank_latest_per_country.csv"
    with out_latest.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["iso2", "iso3",
                    "gdp_per_capita_ppp", "gdp_year",
                    "internet_users_pct", "internet_year",
                    "population", "population_year",
                    "tertiary_education_pct", "tertiary_year"])
        for iso2 in sorted(latest.keys()):
            d = latest[iso2]
            iso3 = canonical.get(iso2, {}).get("iso2", "") or iso2  # fallback
            # Find canonical iso3
            from_canon = next((r for r in csv.DictReader((PA / "countries_canonical.csv").open())
                               if r["iso2"] == iso2), None)
            iso3_v = from_canon["iso3"] if from_canon else ""
            w.writerow([
                iso2, iso3_v,
                d.get("gdp_per_capita_ppp", ("", ""))[0], d.get("gdp_per_capita_ppp", ("", ""))[1],
                d.get("internet_users_pct", ("", ""))[0], d.get("internet_users_pct", ("", ""))[1],
                d.get("population", ("", ""))[0], d.get("population", ("", ""))[1],
                d.get("tertiary_education_pct", ("", ""))[0], d.get("tertiary_education_pct", ("", ""))[1],
            ])
    print(f"Wrote {out_latest} ({len(latest)} countries)")

    # Quick stats
    n_with_all_four = sum(1 for d in latest.values() if len(d) == 4)
    n_with_gdp = sum(1 for d in latest.values() if "gdp_per_capita_ppp" in d)
    n_with_pop = sum(1 for d in latest.values() if "population" in d)
    n_with_int = sum(1 for d in latest.values() if "internet_users_pct" in d)
    print(f"\nLatest-value coverage:")
    print(f"  GDP per capita PPP: {n_with_gdp}")
    print(f"  Internet users pct: {n_with_int}")
    print(f"  Population: {n_with_pop}")
    print(f"  All 4 indicators: {n_with_all_four}")


if __name__ == "__main__":
    main()
