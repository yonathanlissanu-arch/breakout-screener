"""Figure: SMARCA4 homozygous-deletion extents (TCGA pan-cancer) + 19p co-loss in SMARCA4-truncated lung tumors."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GRAY, BLUE, ORANGE, INK, MUTED, GRID = "#8c8b86", "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e6e5e0"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "font.size": 9.5})
genes = pd.read_csv("genes_chr19.csv").set_index("gene")
s4 = genes.loc["SMARCA4", "start"]
ext = pd.read_csv("homdel_extents.csv")
chk = pd.read_csv("homdel_expression_check.csv", index_col=0)
ext["SMARCA4_z"] = ext["sample"].map(chk["SMARCA4"])
ext = ext.sort_values(["size_Mb", "study"], ascending=[False, True]).reset_index(drop=True)
WIN = 1.3

fig, (ax, bx) = plt.subplots(1, 2, figsize=(15, 7.2), gridspec_kw={"width_ratios": [2.1, 1]})
for i, r in ext.iterrows():
    cod = r.codeleted.split(";")
    lo = (genes.loc[cod, "start"].min() - s4) / 1e6; hi = (genes.loc[cod, "end"].max() - s4) / 1e6
    confirmed = r.SMARCA4_z <= -2
    big = r.size_Mb > 2
    col = GRAY if big else (ORANGE if confirmed else BLUE)
    ax.plot([max(lo, -WIN), min(hi, WIN)], [i, i], color=col, lw=5, solid_capstyle="butt", alpha=0.55 if big else 1)
    if lo < -WIN: ax.annotate("", (-WIN - 0.05, i), (-WIN + 0.02, i), arrowprops=dict(arrowstyle="->", color=GRAY, lw=1))
    if hi > WIN: ax.annotate("", (WIN + 0.05, i), (WIN - 0.02, i), arrowprops=dict(arrowstyle="->", color=GRAY, lw=1))
    z = "" if np.isnan(r.SMARCA4_z) else f"z={r.SMARCA4_z:.1f}"
    ax.text(WIN + 0.1, i, f"{r.study}  {r.size_Mb:.1f} Mb  {z}", va="center", fontsize=7.5, color=MUTED)
for gname in ["KEAP1", "DNM2", "CARM1", "YIPF2", "TIMM29", "SMARCA4", "LDLR"]:
    x = (genes.loc[gname, "start"] - s4) / 1e6
    ax.axvline(x, color=INK if gname == "SMARCA4" else GRID, lw=1.2 if gname == "SMARCA4" else 0.9, zorder=0)
pos = lambda g: (genes.loc[g, "start"] - s4) / 1e6
for label, x, y, w in [("KEAP1", pos("KEAP1"), -0.9, "normal"), ("DNM2", pos("DNM2"), -0.9, "normal"),
                       ("LDLR", pos("LDLR"), -0.9, "normal"), ("SMARCA4", 0, -2.0, "bold"),
                       ("CARM1 · YIPF2 · TIMM29", (pos("CARM1") + pos("TIMM29")) / 2, -3.1, "normal")]:
    ax.text(x, y, label, ha="right" if label.startswith("CARM1") else "center", va="bottom", fontsize=8.5, color=INK, fontweight=w)
ax.set_ylim(len(ext) - 0.3, -4.0); ax.set_xlim(-WIN - 0.1, WIN + 0.1)
ax.set_yticks([]); ax.spines["left"].set_visible(False)
ax.set_xlabel("Position relative to SMARCA4 start (Mb, chr19 hg38)")
ax.set_title("A  SMARCA4 homozygous deletions, TCGA pan-cancer (33 tumors, 0.3%)", loc="left", fontsize=11, fontweight="bold")
handles = [plt.Line2D([], [], color=ORANGE, lw=5), plt.Line2D([], [], color=BLUE, lw=5), plt.Line2D([], [], color=GRAY, lw=5, alpha=0.55)]
ax.legend(handles, ["focal, SMARCA4 mRNA z ≤ −2 (confirmed)", "focal, mRNA not clearly lost",
                    "> 2 Mb: essential genes still expressed (not true 0-copy)"],
          frameon=False, loc="upper left", fontsize=8.5, bbox_to_anchor=(0, -0.09), ncol=3)

s = pd.read_csv("lung_smarca4_keap1_summary.csv")
cats = [("pct_SMARCA4_loss_in_truncating", "SMARCA4 2nd-copy loss\n(19p LOH)"), ("pct_KEAP1_loss_in_truncating", "KEAP1 one-copy loss"),
        ("pct_KEAP1_mut_in_truncating", "KEAP1 mutation")]
y = np.arange(len(cats)); h = 0.36
for j, (t, col) in enumerate([("LUAD", ORANGE), ("LUSC", BLUE)]):
    r = s[s.tumor == t].iloc[0]
    vals = [r[c] for c, _ in cats]
    b = bx.barh(y + (j - 0.5) * (h + 0.04), vals, height=h, color=col, label=f"{t} SMARCA4-truncated (n={int(r.SMARCA4_truncating)})")
    for rect, v in zip(b, vals):
        bx.text(v + 1.5, rect.get_y() + rect.get_height() / 2, f"{v:.0f}%", va="center", fontsize=8.5, color=INK)
luad = s[s.tumor == "LUAD"].iloc[0]
bx.text(luad.pct_KEAP1_mut_in_truncating + 12, 2 - 0.5 * (h + 0.04),
        f"vs {luad.pct_KEAP1_mut_in_rest:.0f}% of other LUAD, p = {luad.fisher_p_KEAP1mut:.2f}", va="center", fontsize=8, color=MUTED)
bx.set_yticks(y, [c[1] for c in cats]); bx.invert_yaxis(); bx.set_xlim(0, 100)
bx.set_xlabel("% of SMARCA4-truncated tumors"); bx.grid(axis="x", color=GRID, lw=0.8); bx.set_axisbelow(True)
bx.legend(frameon=False, loc="upper left", fontsize=8.5, bbox_to_anchor=(0, -0.09), ncol=1)
bx.set_title("B  Lung: 19p loss co-hits KEAP1", loc="left", fontsize=11, fontweight="bold")
fig.suptitle("Genes co-deleted with SMARCA4: CARM1 / YIPF2 / TIMM29 and LDLR (focal 0-copy); KEAP1 (one copy, via 19p loss)",
             x=0.01, ha="left", fontsize=12.5)
fig.text(0.01, 0.005, "TCGA PanCancer Atlas via cBioPortal. Homozygous = GISTIC −2; mRNA z vs all tumors in the same study. "
         "One-copy loss = GISTIC ≤ −1. Truncating = nonsense, frameshift, splice site.", fontsize=7.5, color=MUTED)
fig.tight_layout(rect=(0, 0.05, 1, 0.95)); fig.savefig("fig_smarca4_codeletion.png", dpi=200)
