"""
Figure 3 — Ukraine top-10% share time series 2011–2025
Lines: Ukraine with dcua / Ukraine without dcua / Global mean baseline
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE   = "/Users/ss/Library/CloudStorage/OneDrive-SouthPostOakBarberCollege/paper/ctftime-research"
SCORES = f"{BASE}/data/processed/paper_a/event_scores_enriched.csv"
EVENTS = f"{BASE}/data/processed/paper_a/events_master.csv"
OUT_PDF = f"{BASE}/paper/paper_a/figures/fig3_ukraine_timeseries.pdf"
OUT_PNG = f"{BASE}/paper/paper_a/figures/fig3_ukraine_timeseries.png"

DCUA_ID = 762   # CTFtime team_id for dcua

# ── load data ──────────────────────────────────────────────────────────────
scores = pd.read_csv(SCORES, dtype={"team_id": "Int64"})
events = pd.read_csv(EVENTS, usecols=["event_id", "year", "weight", "participants"])

# merge year onto placements
df = scores.merge(events[["event_id", "year"]], on="event_id", how="left")
df = df[df["year"].notna()].copy()
df["year"] = df["year"].astype(int)
df = df[df["year"].between(2011, 2025)].copy()

# event field size (unique teams per event)
event_size = df.groupby("event_id")["team_id"].nunique().rename("field_size")
df = df.merge(event_size, on="event_id", how="left")
df["event_pct"] = 1 - (df["place"] - 1) / (df["field_size"] - 1).clip(lower=1)
df["top10"] = (df["event_pct"] >= 0.90).astype(int)

# ── Ukraine subset ─────────────────────────────────────────────────────────
ua = df[df["country"] == "UA"].copy()
ua_no_dcua = ua[ua["team_id"] != DCUA_ID].copy()

def yearly_top10_share(sub):
    """top10 appearances / total appearances per year, weighted by event size."""
    g = sub.groupby("year").agg(top10=("top10", "sum"), total=("top10", "count"))
    g["share"] = g["top10"] / g["total"].clip(lower=1)
    return g["share"]

ua_share       = yearly_top10_share(ua).rename("Ukraine (with dcua)")
ua_nodcua_share = yearly_top10_share(ua_no_dcua).rename("Ukraine (without dcua)")

# ── global baseline: all countries, all teams ──────────────────────────────
# global baseline: country-tagged placements only (matches fig legend text)
global_df = df[df["country"].notna()].copy()
global_share = yearly_top10_share(global_df).rename("Global mean")

# ── combine ────────────────────────────────────────────────────────────────
ts = pd.concat([ua_share, ua_nodcua_share, global_share], axis=1)
ts = ts.reindex(range(2011, 2026))

# ── figure ─────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 4.5))
fig.subplots_adjust(left=0.10, right=0.96, top=0.87, bottom=0.13)

years = ts.index.to_numpy()

ax.plot(years, ts["Ukraine (with dcua)"] * 100,
        color="#2a9d8f", lw=2.0, marker="o", ms=5, label="Ukraine (all teams, incl. dcua)")
ax.plot(years, ts["Ukraine (without dcua)"] * 100,
        color="#2a9d8f", lw=1.6, marker="o", ms=4.5, linestyle="--",
        label="Ukraine (excl. dcua)", alpha=0.85)
ax.plot(years, ts["Global mean"] * 100,
        color="#e76f51", lw=1.5, marker="s", ms=3.5, linestyle=":",
        label="Global mean (all country-tagged teams)")

# shade the GCI vintage windows
vintage_windows = [
    (2016, 2018, "GCI\n2017"),
    (2019, 2021, "GCI\n2020"),
    (2023, 2025, "GCI\n2024"),
]
colours_w = ["#e9f2fb", "#e9fbf2", "#fdf2e9"]
for (y0, y1, lbl), clr in zip(vintage_windows, colours_w):
    ax.axvspan(y0 - 0.4, y1 + 0.4, alpha=0.35, color=clr, zorder=0)

# dcua annotation — compute dcua appearance share for 2023-2025 window
ua_2024w = ua[ua["year"].between(2023, 2025)]
dcua_share_pct = ua_2024w["team_id"].eq(DCUA_ID).mean() * 100
# point arrow to peak Ukraine year in 2016-2025
peak_year = int(ts["Ukraine (with dcua)"].idxmax())   # full 2011-2025 range
peak_val  = ts.loc[peak_year, "Ukraine (with dcua)"] * 100
ax.annotate(
    f"Peak: {peak_val:.0f}% top-10 share\n({peak_year})\ndcua = {dcua_share_pct:.0f}% of UA appearances\n(2023–2025 window)",
    xy=(peak_year, peak_val),
    xytext=(2020.5, 62),
    fontsize=7.5, ha="left",
    arrowprops=dict(arrowstyle="->", color="#333333", lw=0.8),
    bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.85, ec="#cccccc")
)

ax.set_xlim(2010.5, 2025.5)
ax.set_ylim(0, 75)
ax.set_xticks(range(2011, 2026))
ax.set_xticklabels(range(2011, 2026), rotation=45, ha="right", fontsize=8)
ax.set_yticks(range(0, 80, 10))
ax.set_yticklabels([f"{v}%" for v in range(0, 80, 10)], fontsize=8)
ax.set_xlabel("Year", fontsize=9)
ax.set_ylabel("Share of top-10% event placements", fontsize=9)
ax.legend(fontsize=8, loc="upper left", frameon=True,
          framealpha=0.9, edgecolor="#cccccc")
ax.grid(axis="y", linestyle=":", linewidth=0.5, color="#dddddd", zorder=0)
ax.spines[["top", "right"]].set_visible(False)

# draw vintage labels once at correct y after ylim set
for (y0, y1, lbl), clr in zip(vintage_windows, colours_w):
    ax.text((y0 + y1) / 2, 73, lbl,
            ha="center", va="top", fontsize=7.5, color="#555555")

ax.set_title(
    "Figure 3. Ukraine top-10% CTF placement share, 2011–2025\n"
    "(with and without team dcua; global mean shown as reference)",
    fontsize=9, pad=6
)

plt.savefig(OUT_PDF, format="pdf", dpi=300, bbox_inches="tight")
plt.savefig(OUT_PNG, format="png", dpi=300, bbox_inches="tight")
print(f"Saved: {OUT_PDF}")
print(f"Saved: {OUT_PNG}")
plt.close()
