#!/usr/bin/env python3
"""Workflow figure (new Fig. 1) for the major revision — measurement-to-audit pipeline.
Addresses R1#13 / R2 / EIC request for a workflow figure to aid readability.
Output: paper/paper_a/figures/fig0_workflow.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
OUT = Path(__file__).resolve().parent.parent.parent.parent / "paper/paper_a/figures/fig0_workflow.png"

fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
ax.set_xlim(0, 100); ax.set_ylim(0, 52); ax.axis("off")

C_DATA="#dbe7f3"; C_MEAS="#e6f0e0"; C_DIV="#f6e7d6"; C_AUD="#efe2ef"; EDGE="#33576e"
def box(x,y,w,h,text,fc,fs=8.6,bold=False):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.4,rounding_size=1.4",
                                linewidth=1.1,edgecolor=EDGE,facecolor=fc))
    ax.text(x+w/2,y+h/2,text,ha="center",va="center",fontsize=fs,
            fontweight="bold" if bold else "normal",wrap=True)
def arrow(x1,y1,x2,y2):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-|>",mutation_scale=13,
                                 lw=1.3,color=EDGE,shrinkA=2,shrinkB=2))

# Row 1 — data to performance composite (y≈34)
y1=34; h=11
box(1, y1, 20, h, "Raw CTFtime scoreboards\n2,689 events ·\n749,742 team–event\nplacements", C_DATA, bold=True)
box(26, y1, 18, h, "Event percentile\n$p_{ie}$  (Eq. 2)\nfield-size invariant", C_MEAS)
box(49, y1, 21, h, "Four performance metrics\nmedian + top-10/25/50%\nWilson shrinkage\n(Eq. 3a–3d, Eq. 6)", C_MEAS)
box(75, y1, 23, h, "Within-vintage rank percentile\n→ performance composite\n$V_{cv}$  (Eq. 4–5)", C_MEAS, bold=True)
for x in [(21,26),(44,49),(70,75)]: arrow(x[0],y1+h/2,x[1],y1+h/2)

# down connector
arrow(86.5, y1, 86.5, 26)

# Row 2 — index + divergence (y≈14)
y2=14
box(1, y2, 24, h, "Policy index percentile $I_{cv}$\nGCI 2017 / 2020 / 2024\nNCSI 2026\n(country-name harmonised)", C_DATA, bold=True)
box(60, y2, 27, h, "Divergence  $D_{cv}=V_{cv}-I_{cv}$\n(Eq. 7)  +  within-region (Eq. 8)\nselection model (Eq. 1, diagnostic)", C_DIV, bold=True)
arrow(25, y2+h/2, 60, y2+h/2)
arrow(86.5, 26, 86.5, y2+h)  # composite down into divergence
ax.text(50, y2+h/2+0.3, "scoped estimand\n(§3.4)", ha="center", va="center", fontsize=7.5, style="italic", color="#555")

# Row 3 — five-layer audit (y≈1)
y3=0.5; hb=10
labels=["Layer 1\nGlobal rank ρ\n(convergence)","Layer 2\nWithin-region\nρ","Layer 3\nCountry\ndivergence\n(Table 5/5a)",
        "Layer 4\nAcademic\nsubset","Layer 5\nElite\nconcentration\n(leave-top-1)"]
xw=18.6; x0=2.0; gap=1.0
for i,lab in enumerate(labels):
    box(x0+i*(xw+gap), y3, xw, hb, lab, C_AUD, fs=7.8)
arrow(73.5, y2, 73.5, y3+hb)  # divergence straight down to audit band
ax.text(2, y3+hb+1.4, "Five-layer divergence audit  (decreasing breadth → increasing focus; OECD/JRC logic)",
        ha="left", va="bottom", fontsize=8.2, fontweight="bold", color=EDGE)

plt.tight_layout(pad=0.4)
fig.savefig(OUT, bbox_inches="tight", facecolor="white")
print("wrote", OUT)
