"""Figures + TCGA/SCLC summary tables for the FOCAD / VRK2 lung analysis.

Usage: python3 -P figures.py   (after depmap_build.py, depmap_screen.py, tcga_fetch.py, sclc_fetch.py)
"""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

GRAY, BLUE, ORANGE, INK, MUTED, GRID = "#8c8b86", "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e6e5e0"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "font.size": 9.5})
rng = np.random.default_rng(0)

def title(ax, s):
    ax.set_title(s, loc="left", fontsize=11, fontweight="bold", color=INK)

def grid(ax, axis="y"):
    ax.grid(axis=axis, color=GRID, lw=0.8); ax.set_axisbelow(True)

def strip(ax, groups, colors, lung_masks=None, s=14):
    for i, (vals, col) in enumerate(zip(groups, colors)):
        big = len(vals) > 150
        x = i + rng.uniform(-0.2, 0.2, len(vals))
        ax.scatter(x, vals, s=8 if big else s, color=col, alpha=0.35 if big else 0.8, edgecolor="white", lw=0.4, zorder=3)
        ax.plot([i - 0.28, i + 0.28], [np.median(vals)] * 2, color=INK, lw=2, zorder=4)
        if lung_masks is not None:
            lm = lung_masks[i]
            ax.scatter(x[lm], np.asarray(vals)[lm], s=46, facecolor="none", edgecolor=INK, lw=1.3, zorder=5)

# ---------------- Figure 1: DepMap ----------------
m = pd.read_csv("depmap_crispr_models.csv", index_col=0)
scr = pd.read_csv("depmap_dependency_screen.csv")
order = ["FOCAD-intact", "MTAP-del, FOCAD-intact", "FOCAD-deleted"]
gcol = [GRAY, BLUE, ORANGE]
fig, axes = plt.subplots(1, 4, figsize=(17, 4.8), gridspec_kw={"width_ratios": [1.15, 1, 1, 1.15]})

ax = axes[0]
r = scr[scr.comparison == "FOCAD-del vs MTAP-del/FOCAD-intact (pan-cancer)"].copy()
r["nlp"] = -np.log10(r.p)
sig = r.fdr < 0.05
ax.scatter(r.loc[~sig, "diff"], r.loc[~sig, "nlp"], s=5, color=GRAY, alpha=0.4, lw=0)
neg, pos = sig & (r["diff"] < 0), sig & (r["diff"] > 0)
ax.scatter(r.loc[neg, "diff"], r.loc[neg, "nlp"], s=26, color=ORANGE, edgecolor="white", lw=0.5, zorder=3)
ax.scatter(r.loc[pos, "diff"], r.loc[pos, "nlp"], s=16, color=BLUE, edgecolor="white", lw=0.5, zorder=3)
for _, row in r[neg].iterrows():
    ax.annotate(row.gene, (row["diff"], row.nlp), xytext=(6, 0), textcoords="offset points", fontsize=9.5, color=INK, va="center")
ax.annotate(f"{int(pos.sum())} genes inside the deletion\n(IFNA cluster, FOCAD, HACD4…):\nno target left to knock out",
            tuple(r.loc[pos].nsmallest(1, "nlp")[["diff", "nlp"]].iloc[0]), xytext=(0.04, 0.40), textcoords="axes fraction", ha="left",
            fontsize=8, color=MUTED, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.7))
ax.set_xlabel("Δ gene effect (FOCAD-del − MTAP-del/FOCAD-intact)\n← more essential in FOCAD-deleted")
ax.set_ylabel("−log10 p (Welch t)"); grid(ax, "both")
title(ax, "A  Genome-wide screen (pan-cancer)")
ax.text(0.02, 0.98, f"{int(r.n_test.iloc[0])} FOCAD-del vs {int(r.n_control.iloc[0])} MTAP-del lines\ncolored = FDR < 0.05",
        transform=ax.transAxes, va="top", fontsize=8.5, color=MUTED)

for ax, g, lab in [(axes[1], "PELO", "B"), (axes[2], "HBS1L", "C")]:
    vals = [m.loc[m.FOCAD_group == k, f"{g}_effect"].dropna() for k in order]
    lung = [(m.loc[v.index, "OncotreeLineage"] == "Lung").values for v in vals]
    strip(ax, [v.values for v in vals], gcol, lung)
    ax.set_xticks(range(3), [f"FOCAD\nintact\n(n={len(vals[0])})", f"MTAP-del,\nFOCAD intact\n(n={len(vals[1])})",
                             f"FOCAD\ndeleted\n(n={len(vals[2])})"])
    ax.set_ylabel(f"{g} CRISPR gene effect (Chronos)"); grid(ax)
    ax.axhline(-1, color=MUTED, lw=0.8, ls="--"); ax.text(2.45, -1, "common-essential\nmedian", fontsize=7.5, color=MUTED, va="center")
    p = stats.mannwhitneyu(vals[2], vals[1]).pvalue
    title(ax, f"{lab}  {g} dependency")
    ax.text(0.02, 0.02, f"FOCAD-del vs MTAP-del p = {p:.1g}\n○ = lung cell lines", transform=ax.transAxes, fontsize=8.5, color=MUTED)

ax = axes[3]
x = m.dropna(subset=["VRK2_expr", "VRK1_effect"])
lung = x.OncotreeLineage == "Lung"
ax.scatter(x.loc[~lung, "VRK2_expr"], x.loc[~lung, "VRK1_effect"], s=8, color=GRAY, alpha=0.45, lw=0)
ax.scatter(x.loc[lung, "VRK2_expr"], x.loc[lung, "VRK1_effect"], s=22, color=BLUE, edgecolor="white", lw=0.5, zorder=3, label="Lung lines")
for mid, row in x[lung & (x.VRK2_expr < 2)].iterrows():
    ax.annotate(row.CellLineName, (row.VRK2_expr, row.VRK1_effect), xytext=(6, -2), textcoords="offset points", fontsize=8, color=INK)
ax.axvline(2, color=MUTED, lw=0.8, ls="--"); ax.text(1.9, ax.get_ylim()[1], "VRK2-low", ha="right", va="top", fontsize=8, color=MUTED)
rho = stats.spearmanr(x.VRK2_expr, x.VRK1_effect).statistic
ax.set_xlabel("VRK2 mRNA, log2(TPM + 1)"); ax.set_ylabel("VRK1 CRISPR gene effect"); grid(ax, "both")
ax.legend(frameon=False, loc="lower right", fontsize=8.5)
title(ax, "D  VRK2 loss → VRK1 dependency")
ax.text(0.02, 0.02, f"all lines Spearman ρ = {rho:.2f}", transform=ax.transAxes, fontsize=8.5, color=MUTED)
fig.suptitle("DepMap 24Q4: FOCAD-deleted lines depend on PELO/HBS1L; VRK2-low lines on VRK1", x=0.01, ha="left", fontsize=13)
fig.tight_layout(rect=(0, 0, 1, 0.95)); fig.savefig("fig1_depmap.png", dpi=200); plt.close(fig)

# ---------------- TCGA / SCLC summaries ----------------
t = pd.read_csv("tcga_lung.csv")
c = t.dropna(subset=["FOCAD_gistic"])
rows = []
for tt, g in c.groupby("tumor_type"):
    n = len(g); fd = g.FOCAD_gistic == -2
    rows.append(dict(cohort=f"TCGA {tt}", n=n,
                     FOCAD_homdel=int(fd.sum()), FOCAD_homdel_pct=100 * fd.mean(),
                     MTAP_homdel_pct=100 * (g.MTAP_gistic == -2).mean(), CDKN2A_homdel_pct=100 * (g.CDKN2A_gistic == -2).mean(),
                     FOCAD_homdel_with_MTAP_homdel=int((fd & (g.MTAP_gistic == -2)).sum()),
                     FOCAD_shallow_del_pct=100 * (g.FOCAD_gistic == -1).mean(),
                     FOCAD_truncating_mutations=int(g.FOCAD_mutation.fillna("").str.contains("Splice_Site|Nonsense|Frame_Shift").sum()),
                     VRK2_homdel=int((g.VRK2_gistic == -2).sum())))
freq = pd.DataFrame(rows)

def vrk2_low(log2vals):
    rel = log2vals - np.nanmedian(log2vals)
    return rel, (rel <= -3)
tv = t.dropna(subset=["VRK2_rsem"])
vr = {}
for tt, g in tv.groupby("tumor_type"):
    rel, low = vrk2_low(np.log2(g.VRK2_rsem.values + 1)); vr[f"TCGA {tt}\n(NSCLC)"] = rel
    freq.loc[freq.cohort == f"TCGA {tt}", ["VRK2_low_8fold", "VRK2_low_8fold_pct"]] = [low.sum(), 100 * low.mean()]
sc = pd.read_csv("sclc_ucologne_expression.csv", index_col=0)
rel, low = vrk2_low(np.log2(sc.VRK2.values + 0.1)); vr["U Cologne\n(SCLC)"] = rel
focad_sclc = np.log2(sc.FOCAD.values + 0.1) - np.median(np.log2(sc.FOCAD.values + 0.1))
freq = pd.concat([freq, pd.DataFrame([dict(cohort="U Cologne SCLC (expression only)", n=len(sc),
                                           VRK2_low_8fold=int(low.sum()), VRK2_low_8fold_pct=100 * low.mean())])])
freq.round(2).to_csv("tumor_frequencies.csv", index=False)

# ---------------- Figure 2: tumors ----------------
fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.8), gridspec_kw={"width_ratios": [1, 1.2, 1.1]})
ax = axes[0]
f2 = freq[freq.cohort.str.startswith("TCGA")]
xs = np.arange(len(f2)); w = 0.26
for j, (col, lab, colr) in enumerate([("CDKN2A_homdel_pct", "CDKN2A", GRAY), ("MTAP_homdel_pct", "MTAP", BLUE),
                                     ("FOCAD_homdel_pct", "FOCAD", ORANGE)]):
    b = ax.bar(xs + (j - 1) * (w + 0.02), f2[col], width=w, color=colr, label=lab)
    for rect, v in zip(b, f2[col]):
        ax.text(rect.get_x() + rect.get_width() / 2, v + 0.4, f"{v:.1f}%", ha="center", fontsize=8.5, color=INK)
ax.set_xticks(xs, [f"{c.replace('TCGA ', '')}\n(n={n})" for c, n in zip(f2.cohort, f2.n)])
ax.set_ylabel("Homozygous deletion (GISTIC −2), % tumors"); grid(ax)
ax.legend(frameon=False, title="9p21 gene", fontsize=8.5, title_fontsize=8.5)
title(ax, "A  9p21 deep deletions, TCGA")
ax.text(0.02, 0.98, "every FOCAD deletion also\nremoves MTAP and CDKN2A", transform=ax.transAxes, va="top", fontsize=8.5, color=MUTED)

ax = axes[1]
lab_map = {-2: "Deep\ndel", -1: "Shallow\ndel", 0: "Neutral", 1: "Gain"}
groups, labels, cols = [], [], []
for tt in ["LUAD", "LUSC"]:
    g = c[c.tumor_type == tt]
    for k in [0, -1, -2]:
        v = np.log2(g.loc[g.FOCAD_gistic == k, "FOCAD_rsem"].dropna() + 1).values
        groups.append(v); labels.append(f"{tt}\n{lab_map[k]}\n(n={len(v)})"); cols.append(ORANGE if k == -2 else GRAY)
strip(ax, groups, cols)
ax.set_xticks(range(len(groups)), labels, fontsize=8.5); ax.set_ylabel("FOCAD mRNA, log2(RSEM + 1)"); grid(ax)
title(ax, "B  FOCAD expression by copy number")

ax = axes[2]
names = list(vr)
strip(ax, [vr[k] for k in names], [GRAY, GRAY, ORANGE])
ax.axhline(-3, color=MUTED, lw=0.8, ls="--"); ax.text(2.45, -3.15, "8-fold below\ncohort median", fontsize=7.5, color=MUTED, va="top")
lows = [(vr[k] <= -3).sum() for k in names]
ax.set_xticks(range(3), [f"{k}\n{l}/{len(vr[k])} low" for k, l in zip(names, lows)])
ax.set_ylabel("VRK2 mRNA, log2 fold vs cohort median"); grid(ax)
title(ax, "C  VRK2 loss: absent in NSCLC, ~6% of SCLC")
fig.suptitle("Lung tumors: FOCAD deletion in ~5–6% of NSCLC; VRK2 deficiency confined to small-cell", x=0.01, ha="left", fontsize=13)
fig.text(0.01, 0.005, "Sources: TCGA PanCancer Atlas LUAD/LUSC and U Cologne SCLC (George 2015) via cBioPortal. SCLC values are FPKM; "
         "TCGA are RSEM — compare within cohorts, not across.", fontsize=7.5, color=MUTED)
fig.tight_layout(rect=(0, 0.03, 1, 0.95)); fig.savefig("fig2_tumors.png", dpi=200); plt.close(fig)
pd.set_option("display.width", 250); print(freq.round(1).to_string(index=False))
