"""
Figure 2 — Headline divergence cases: stability across GCI vintages (dot-and-range)
5 pre-specified §6.4 headline countries (UKR, ARG, MYS, SAU, THA).
Dot = mean D_cv across GCI 2017/2020/2024; horizontal line = min–max range.
Additional marker: individual vintage dots in lighter colour.
Positive D_cv = CTF performance exceeds index; negative = under-performance.
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

BASE    = "/Users/ss/Library/CloudStorage/OneDrive-SouthPostOakBarberCollege/paper/ctftime-research"
AUDIT   = f"{BASE}/data/processed/paper_a/outlier_concentration_audit.csv"
OUT_PDF = f"{BASE}/paper/paper_a/figures/fig2_divergence_bar.pdf"
OUT_PNG = f"{BASE}/paper/paper_a/figures/fig2_divergence_bar.png"

# ── data ───────────────────────────────────────────────────────────────────
df = pd.read_csv(AUDIT)

HEADLINE_ISO2 = {"UA": "Ukraine",  "AR": "Argentina",
                 "MY": "Malaysia", "SA": "Saudi Arabia", "TH": "Thailand"}

gci = df[
    (df["source"] == "GCI") &
    (df["inclusion_tier"] == "main") &
    (df["iso2"].isin(HEADLINE_ISO2))
].copy()
gci["country_label"] = gci["iso2"].map(HEADLINE_ISO2)

# summary per country
summ = (
    gci.groupby(["iso2", "country_label", "pattern"])
    .agg(
        mean_div=("divergence_performance_full", "mean"),
        min_div =("divergence_performance_full", "min"),
        max_div =("divergence_performance_full", "max"),
        n_v     =("vintage_year", "nunique"),
    )
    .reset_index()
    .sort_values("mean_div")
    .reset_index(drop=True)
)

# per-vintage rows for individual dot markers
gci_pv = gci[["iso2", "country_label", "pattern", "vintage_year",
              "divergence_performance_full"]].copy()

# ── colours ────────────────────────────────────────────────────────────────
POS_CLR  = "#2a9d8f"   # teal — over-performing
NEG_CLR  = "#e76f51"   # coral — under-performing
POS_LITE = "#a8d8d3"
NEG_LITE = "#f4b8a5"
VINTAGE_MARKERS = {2017: "o", 2020: "s", 2024: "^"}

def clr(pattern, lite=False):
    if pattern == "positive":
        return POS_LITE if lite else POS_CLR
    return NEG_LITE if lite else NEG_CLR

# ── figure (single Elsevier column: 88 mm ≈ 3.46 in) ──────────────────────
fig, ax = plt.subplots(figsize=(6.0, 3.6))
fig.subplots_adjust(left=0.22, right=0.96, top=0.84, bottom=0.18)

y_pos = np.arange(len(summ))

for yi, row in summ.iterrows():
    c_main = clr(row["pattern"])
    c_lite = clr(row["pattern"], lite=True)

    # range line
    ax.plot(
        [row["min_div"], row["max_div"]], [yi, yi],
        color=c_main, lw=3.0, alpha=0.55, solid_capstyle="round", zorder=2
    )

    # individual vintage dots
    pv = gci_pv[gci_pv["iso2"] == row["iso2"]]
    for _, pvr in pv.iterrows():
        mk = VINTAGE_MARKERS.get(int(pvr["vintage_year"]), "o")
        ax.scatter(
            pvr["divergence_performance_full"], yi,
            s=28, color=c_lite, marker=mk,
            edgecolors=c_main, linewidths=0.7, zorder=3
        )

    # mean dot (larger, filled)
    ax.scatter(
        row["mean_div"], yi,
        s=70, color=c_main,
        edgecolors="white", linewidths=0.8, zorder=4
    )

    # value label
    ha = "left" if row["mean_div"] >= 0 else "right"
    offset = 3 if row["mean_div"] >= 0 else -3
    sign   = "+" if row["mean_div"] >= 0 else ""
    ax.text(
        row["mean_div"] + offset, yi,
        f"{sign}{row['mean_div']:.1f}",
        va="center", ha=ha, fontsize=7.5, color="#333333"
    )

# zero line
ax.axvline(0, color="#333333", lw=0.9, zorder=1)

# axes
ax.set_yticks(y_pos)
ax.set_yticklabels(summ["country_label"], fontsize=9)
ax.set_xlabel(
    r"Divergence $D_{cv}$: CTF performance percentile $-$ index percentile",
    fontsize=8.5
)
ax.set_xlim(-105, 65)
ax.tick_params(axis="x", labelsize=8)
ax.grid(axis="x", linestyle=":", linewidth=0.5, color="#dddddd", zorder=0)
ax.spines[["top", "right"]].set_visible(False)

# horizontal separator between positive / negative groups
pos_y = summ[summ["pattern"] == "positive"].index.min()
ax.axhline(pos_y - 0.5, color="#bbbbbb", lw=0.8, linestyle="--")

# ── legend ─────────────────────────────────────────────────────────────────
from matplotlib.lines import Line2D

legend_handles = [
    mpatches.Patch(facecolor=POS_CLR, label="Over-performing (CTF > Index)"),
    mpatches.Patch(facecolor=NEG_CLR, label="Under-performing (CTF < Index)"),
]
# vintage markers
for yr, mk in VINTAGE_MARKERS.items():
    legend_handles.append(
        Line2D([0], [0], marker=mk, color="w",
               markerfacecolor="#888888", markeredgecolor="#888888",
               markersize=5.5, label=f"GCI {yr}")
    )
legend_handles.append(
    Line2D([0], [0], marker="o", color="w",
           markerfacecolor="#555555", markeredgecolor="white",
           markersize=7, label="Mean across vintages")
)

ax.legend(
    handles=legend_handles, fontsize=7,
    loc="lower right", frameon=True,
    framealpha=0.92, edgecolor="#cccccc",
    ncol=1, handlelength=1.2
)

# ── title ──────────────────────────────────────────────────────────────────
ax.set_title(
    "Figure 2. Stability of headline divergence across GCI vintages\n"
    "(dot = mean; line = vintage range; GCI 2017/2020/2024 main sample)",
    fontsize=8.5, pad=6
)

plt.savefig(OUT_PDF, format="pdf", dpi=300, bbox_inches="tight")
plt.savefig(OUT_PNG, format="png", dpi=300, bbox_inches="tight")
print(f"Saved: {OUT_PDF}")
print(f"Saved: {OUT_PNG}")
plt.close()
