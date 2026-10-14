"""Figure: SMARCA4 deficiency, metabolic gene expression, and OXPHOS/SMARCA2 dependency (DepMap NSCLC + TCGA LUAD)."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GRAY, BLUE, ORANGE, GREEN, INK, MUTED, GRID = "#8c8b86", "#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b", "#52514e", "#e6e5e0"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "font.size": 9.5})
rng = np.random.default_rng(0)
def title(ax, s): ax.set_title(s, loc="left", fontsize=11, fontweight="bold", color=INK)

lines = pd.read_csv("depmap_nsclc_lines.csv", index_col=0)
de = pd.read_csv("depmap_expression_de.csv", index_col=0)
tc = pd.read_csv("tcga_luad_gene_stats.csv").set_index("gene")

fig, axes = plt.subplots(1, 4, figsize=(18, 5.2), gridspec_kw={"width_ratios": [1.15, 1.25, 1.25, 1.0]})

# A: metabolic gene-set shift (cell lines)
st = pd.read_csv("depmap_expression_gene_sets.csv").set_index("gene_set")
show = ["Glycolysis (core enzymes)", "Glucose uptake (GLUTs)", "Glutaminolysis", "TCA cycle",
        "Mito biogenesis / OXPHOS TFs", "Pentose phosphate", "OXPHOS (all nuclear subunits)", "Glycogen"]
st = st.loc[[s for s in show if s in st.index]].sort_values("mean_t")
ax = axes[0]; y = np.arange(len(st))
cols = [ORANGE if t < 0 else BLUE for t in st.mean_t]
ax.barh(y, st.mean_t, color=cols, height=0.68)
for i, (nm, r) in enumerate(st.iterrows()):
    sig = "*" if r.p_vs_all_genes < 0.05 else ""
    ax.text(r.mean_t + (-0.03 if r.mean_t < 0 else 0.03), i, f"{nm}{sig}", va="center",
            ha="right" if r.mean_t < 0 else "left", fontsize=8.3, color=INK)
ax.axvline(0, color=INK, lw=0.8); ax.set_yticks([]); ax.set_xlim(-2.2, 1.4)
ax.set_xlabel("mean t-statistic across set\n← lower in SMARCA4-deficient")
title(ax, "A  Metabolic gene sets (cell lines)")
ax.text(0.02, 0.02, "* set shifted vs all genes (MWU p<0.05)", transform=ax.transAxes, fontsize=8, color=MUTED)

# B & C: key genes, cell lines and TCGA
genesB = ["ALDOC", "FBP1", "ENO2", "SLC2A1", "HK2", "ESRRA", "MPC1", "PFKM", "HIF1A", "VEGFA", "LDHA", "GAPDH", "PKM", "ALDOA"]
ax = axes[1]
d = de.loc[[g for g in genesB if g in de.index]]
y = np.arange(len(d))
ax.barh(y, d["diff"], color=[ORANGE if v < 0 else BLUE for v in d["diff"]], height=0.66)
for i, (g, r) in enumerate(d.iterrows()):
    s = "***" if r.fdr < 0.01 else "**" if r.fdr < 0.05 else "*" if r.fdr < 0.1 else ""
    ax.text(r["diff"] + (-0.04 if r["diff"] < 0 else 0.04), i, f"{g}{s}", va="center",
            ha="right" if r["diff"] < 0 else "left", fontsize=8.3, color=INK)
ax.axvline(0, color=INK, lw=0.8); ax.set_yticks([]); ax.invert_yaxis(); ax.set_xlim(-2.3, 0.9)
ax.set_xlabel("Δ log2(TPM+1), deficient − WT")
title(ax, "B  Metabolic genes (cell lines)")
ax.text(0.02, 0.02, "FDR: *<0.1 **<0.05 ***<0.01", transform=ax.transAxes, fontsize=8, color=MUTED)

ax = axes[2]
t = tc.loc[[g for g in genesB if g in tc.index]]
y = np.arange(len(t))
ax.barh(y, t["diff"], color=[ORANGE if v < 0 else BLUE for v in t["diff"]], height=0.66)
for i, (g, r) in enumerate(t.iterrows()):
    s = "***" if r.adj_p < 0.01 else "**" if r.adj_p < 0.05 else "*" if r.adj_p < 0.1 else ""
    ax.text(r["diff"] + (-0.02 if r["diff"] < 0 else 0.02), i, f"{g}{s}", va="center",
            ha="right" if r["diff"] < 0 else "left", fontsize=8.3, color=INK)
ax.axvline(0, color=INK, lw=0.8); ax.set_yticks([]); ax.invert_yaxis(); ax.set_xlim(-1.3, 1.5)
ax.set_xlabel("Δ mRNA z-score, deficient − WT")
title(ax, "C  Same genes in TCGA LUAD tumors")
ax.text(0.03, 0.30, "concordant (down in both):\nFBP1, ENO2, ESRRA, VEGFA\n\ndiscordant (↑ in tumors):\nSLC2A1, LDHA, GAPDH, PKM",
        transform=ax.transAxes, fontsize=7.6, color=MUTED, ha="left", va="top")

# D: dependencies
ax = axes[3]
dep = pd.read_csv("depmap_crispr_de.csv", index_col=0)
sm = pd.read_csv("depmap_nsclc_lines.csv", index_col=0)
ge = pd.read_csv("/tmp/claude-0/-home-user-breakout-screener/a3a4833f-dd0e-5c0c-87d2-5e17321c481b/scratchpad/depmap24q4/CRISPRGeneEffect.csv", index_col=0)
ge.columns = [c.split(" (")[0] for c in ge.columns]
grp = sm[sm.group != "excluded"]
vals, labs, cols = [], [], []
for g, k in [("SMARCA4-deficient", 1), ("SMARCA4-WT", 0)]:
    idx = grp.index[grp.group == g].intersection(ge.index)
    vals.append(ge.loc[idx, "SMARCA2"].dropna().values)
    labs.append(f"{g.replace('SMARCA4-','')}\n(n={len(vals[-1])})"); cols.append(ORANGE if k else GRAY)
for i, (v, c) in enumerate(zip(vals, cols)):
    ax.scatter(i + rng.uniform(-0.18, 0.18, len(v)), v, s=26, color=c, alpha=0.8, edgecolor="white", lw=0.5, zorder=3)
    ax.plot([i - 0.28, i + 0.28], [np.median(v)] * 2, color=INK, lw=2, zorder=4)
ax.axhline(-1, color=MUTED, lw=0.8, ls="--"); ax.text(1.46, -1, "common-\nessential", fontsize=7.3, color=MUTED, va="center")
ax.axhline(0, color=MUTED, lw=0.6)
ax.set_xticks([0, 1], labs); ax.set_ylabel("SMARCA2 CRISPR gene effect")
from scipy import stats
p = stats.mannwhitneyu(vals[0], vals[1]).pvalue
title(ax, "D  SMARCA2 paralog dependency")
ax.text(0.02, 0.02, f"p = {p:.0e}  (FDR 0.004)\nthe clean genetic SL;\nOXPHOS subunits only weakly\nskewed (60/97 lower, n.s.)",
        transform=ax.transAxes, fontsize=7.8, color=MUTED, va="bottom")
fig.suptitle("SMARCA4-deficient NSCLC: loss of specific glucose-handling genes (ALDOC, FBP1, GLUT1, ESRRA) and a SMARCA2 paralog dependency",
             x=0.01, ha="left", fontsize=12.5)
fig.text(0.01, 0.005, "DepMap 24Q4 NSCLC cell lines (35 SMARCA4-deficient vs 102 WT) and TCGA LUAD (38 vs 384). Deficient = SMARCA4 LoF mutation "
         "(or truncating in TCGA) or low/absent SMARCA4 mRNA. Welch t; TCGA adjusted for STK11/KEAP1.", fontsize=7.3, color=MUTED)
fig.tight_layout(rect=(0, 0.02, 1, 0.94)); fig.savefig("fig_smarca4_oxphos.png", dpi=200)
