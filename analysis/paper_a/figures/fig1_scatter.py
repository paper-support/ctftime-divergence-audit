"""
Figure 1 — Index vs CTF Performance Scatter (4-facet)
X: index_percentile (within-vintage)
Y: performance_composite_pct (within-vintage)
4 facets: GCI 2017 / GCI 2020 / GCI 2024 / NCSI 2026
Colour: UN M49 region (colorblind-safe Set2 palette)
Labelled outliers: Ukraine, Argentina, Malaysia, Saudi Arabia, Thailand
Diagonal reference line y = x
Spearman rho + 95% CI per facet caption
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

# ── paths ──────────────────────────────────────────────────────────────────
BASE = "/Users/ss/Library/CloudStorage/OneDrive-SouthPostOakBarberCollege/paper/ctftime-research"
PANEL = f"{BASE}/data/processed/paper_a/rq_a1_vintage_panel_robust_perf_region.csv"
BOOT  = f"{BASE}/data/processed/paper_a/spearman_bootstrap.csv"
OUT_PDF = f"{BASE}/paper/paper_a/figures/fig1_scatter.pdf"
OUT_PNG = f"{BASE}/paper/paper_a/figures/fig1_scatter.png"

# ── data ───────────────────────────────────────────────────────────────────
panel = pd.read_csv(PANEL)
boot  = pd.read_csv(BOOT)
main  = panel[(panel["inclusion_tier"] == "main") & (panel["has_both"] == True)].copy()

VINTAGES = [
    ("GCI",  2017, "GCI 2017\n(CTF window 2016–2018)"),
    ("GCI",  2020, "GCI 2020\n(CTF window 2019–2021)"),
    ("GCI",  2024, "GCI 2024\n(CTF window 2023–2025)"),
    ("NCSI", 2026, "NCSI 2026\n(CTF window 2024–2026)"),
]

# headline outlier labels
OUTLIERS = {
    "UKR": "Ukraine",
    "ARG": "Argentina",
    "MYS": "Malaysia",
    "SAU": "Saudi Arabia",
    "THA": "Thailand",
}

# ── region → colour (colorblind-safe Set2 / hand-picked) ───────────────────
REGION_COLOURS = {
    "Eastern Asia":           "#4daf4a",   # green
    "South-eastern Asia":     "#a6d96a",   # light green
    "Southern Asia":          "#984ea3",   # purple
    "Western Asia":           "#d97b5a",   # warm orange
    "Eastern Europe":         "#377eb8",   # blue
    "Western Europe":         "#74b3e8",   # light blue
    "Northern Europe":        "#5c9fd4",
    "Southern Europe":        "#3e7fbf",
    "Northern America":       "#ff7f00",   # orange
    "South America":          "#fdbf6f",   # light orange
    "Central America":        "#e07b54",
    "Northern Africa":        "#e41a1c",   # red
    "Australia and New Zealand": "#a65628",  # brown
    "Other / Unknown":        "#999999",
}

def region_colour(r):
    if pd.isna(r):
        return REGION_COLOURS["Other / Unknown"]
    return REGION_COLOURS.get(str(r), REGION_COLOURS["Other / Unknown"])

# ── bootstrap stats lookup ─────────────────────────────────────────────────
def get_rho(source, year):
    row = boot[(boot["source"] == source) & (boot["vintage_year"] == year)]
    if row.empty:
        return None, None, None
    r = row.iloc[0]
    return r["spearman_rho"], r["spearman_rho_ci_low"], r["spearman_rho_ci_high"]

# ── manual label offsets to avoid overlap ─────────────────────────────────
# (dx_pts, dy_pts, ha, va)  in data units
OFFSETS = {
    "UKR": (4, -8, "left",  "top"),
    "ARG": (4, -4, "left",  "top"),
    "MYS": (-4, -4, "right", "top"),
    "SAU": (-4,  4, "right", "bottom"),
    "THA": ( 4,  4, "left",  "bottom"),
}

# ── figure setup ───────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 4, figsize=(14, 4.2), sharey=False)
fig.subplots_adjust(wspace=0.38, left=0.07, right=0.97, top=0.88, bottom=0.16)

for ax, (src, yr, title) in zip(axes, VINTAGES):
    sub = main[(main["source"] == src) & (main["vintage_year"] == yr)].copy()
    sub["_colour"] = sub["un_region"].apply(region_colour)

    # scatter
    ax.scatter(
        sub["index_percentile"],
        sub["performance_composite_pct"],
        c=sub["_colour"],
        s=40, alpha=0.82, linewidths=0.4, edgecolors="white", zorder=3
    )

    # diagonal reference line
    ax.plot([0, 100], [0, 100], color="#aaaaaa", lw=0.9,
            linestyle="--", zorder=1, label="y = x")

    # outlier labels
    for iso, name in OUTLIERS.items():
        row = sub[sub["iso3"] == iso]
        if row.empty:
            continue
        x = row["index_percentile"].values[0]
        y = row["performance_composite_pct"].values[0]
        dx, dy, ha, va = OFFSETS.get(iso, (4, 4, "left", "bottom"))
        # clamp labels to inside axes
        if y > 95:
            dy, va = -8, "top"
        if x > 95:
            dx, ha = -4, "right"
        ax.scatter(x, y, s=65, c="#e41a1c", zorder=5,
                   linewidths=0.7, edgecolors="white")
        short = name if name != "Saudi Arabia" else "S. Arabia"
        ax.annotate(
            short, (x, y),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=6.5, ha=ha, va=va, zorder=6,
            annotation_clip=True,
            arrowprops=dict(arrowstyle="-", color="#555555", lw=0.5),
            bbox=dict(boxstyle="round,pad=0.15", fc="white", alpha=0.7, ec="none")
        )

    # Spearman rho annotation
    rho, ci_lo, ci_hi = get_rho(src, yr)
    if rho is not None:
        sign = "+" if rho >= 0 else ""
        rho_str = (f"ρ = {sign}{rho:.3f}\n"
                   f"95% CI [{ci_lo:+.2f}, {ci_hi:+.2f}]")
        ax.text(0.03, 0.97, rho_str, transform=ax.transAxes,
                fontsize=7.2, va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.85, ec="#cccccc"),
                fontfamily="monospace")

    # formatting
    ax.set_xlim(-2, 102)
    ax.set_ylim(-2, 102)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.tick_params(labelsize=8)
    ax.set_title(title, fontsize=8.5, pad=4)
    ax.set_xlabel("Index percentile (within-vintage)", fontsize=8)
    if ax is axes[0]:
        ax.set_ylabel("CTF performance percentile\n(within-vintage)", fontsize=8)
    ax.grid(True, linestyle=":", linewidth=0.5, color="#dddddd", zorder=0)
    ax.set_aspect("equal", adjustable="box")

# ── legend: regions ────────────────────────────────────────────────────────
region_order = [
    "Eastern Asia", "South-eastern Asia", "Southern Asia", "Western Asia",
    "Eastern Europe", "Western Europe", "Northern Europe", "Southern Europe",
    "Northern America", "South America", "Northern Africa",
    "Australia and New Zealand",
]
legend_handles = [
    mpatches.Patch(facecolor=REGION_COLOURS[r], label=r, linewidth=0)
    for r in region_order if r in REGION_COLOURS
]
legend_handles.append(
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#e41a1c",
           markersize=6, label="Headline outlier")
)
legend_handles.append(
    Line2D([0], [0], color="#aaaaaa", lw=1, linestyle="--", label="y = x (perfect alignment)")
)

fig.legend(
    handles=legend_handles, loc="lower center",
    ncol=7, fontsize=7, frameon=True,
    bbox_to_anchor=(0.5, -0.01),
    columnspacing=0.8, handlelength=1.2, handletextpad=0.4
)

fig.suptitle(
    "Figure 1. Index percentile vs CTF performance percentile by vintage\n"
    "(main sample, within-vintage rank transforms; diagonal = perfect alignment)",
    fontsize=9, y=0.97
)

plt.savefig(OUT_PDF, format="pdf", dpi=300, bbox_inches="tight")
plt.savefig(OUT_PNG, format="png", dpi=300, bbox_inches="tight")
print(f"Saved: {OUT_PDF}")
print(f"Saved: {OUT_PNG}")
plt.close()
