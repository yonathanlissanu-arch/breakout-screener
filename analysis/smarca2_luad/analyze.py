"""Plot SMARCA2 expression by SMARCA4 status (TCGA LUAD tumors, CCLE LUAD lines) and compare groups."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

ORDER = ["WT", "Missense/other", "Truncating"]
COL = {"WT": "#8c8b86", "Missense/other": "#2a78d6", "Truncating": "#eb6834"}
ANALYSES = {
    "mrna": dict(col="smarca2", log=True, unit="mRNA", out="smarca2_by_smarca4_luad",
                 source="cBioPortal — TCGA PanCancer Atlas LUAD; CCLE (Broad 2019), OncoTree LUAD",
                 sets=[("TCGA LUAD tumors", "tcga_luad.csv", "log2(RSEM + 1)"),
                       ("CCLE LUAD cell lines", "ccle_luad.csv", "log2(RPKM + 1)")]),
    "protein": dict(col="smarca2_protein", log=False, unit="protein", out="smarca2_protein_by_smarca4_luad",
                    source="CPTAC LUAD (Gillette 2020, UMich TMT); CCLE proteomics (Nusinow 2020), OncoTree LUAD",
                    sets=[("CPTAC LUAD tumors", "cptac_luad_protein.csv", "log2 TMT ratio"),
                          ("CCLE LUAD cell lines", "ccle_luad_protein.csv", "log2 TMT ratio (normalized)")]),
}

def cliffs(a, b):
    u = stats.mannwhitneyu(a, b).statistic
    return 2 * u / (len(a) * len(b)) - 1

def run(col, log, unit, out, source, sets):
    rows = []
    fig, axes = plt.subplots(1, 2, figsize=(10, 5.2))
    rng = np.random.default_rng(0)
    for ax, (title, f, ylab) in zip(axes, sets):
        d = pd.read_csv(f); d["y"] = np.log2(d[col] + 1) if log else d[col]
        g = {k: d.loc[d.smarca4 == k, "y"].values for k in ORDER}
        ax.boxplot([g[k] for k in ORDER], positions=range(3), widths=0.5, showfliers=False,
                   medianprops=dict(color="#0b0b0b", lw=2), boxprops=dict(color="#52514e"),
                   whiskerprops=dict(color="#52514e"), capprops=dict(color="#52514e"))
        for i, k in enumerate(ORDER):
            ax.scatter(i + rng.uniform(-0.17, 0.17, len(g[k])), g[k], s=16 if len(g[k]) > 100 else 28,
                       color=COL[k], alpha=0.55 if len(g[k]) > 100 else 0.85, edgecolor="white", lw=0.5, zorder=3)
        ax.set_xticks(range(3), [f"{k}\n(n={len(g[k])})" for k in ORDER])
        ax.set_ylabel(f"SMARCA2 {unit}, {ylab}"); ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", color="#e6e5e0", lw=0.8); ax.set_axisbelow(True)
        mut = np.concatenate([g["Missense/other"], g["Truncating"]])
        kw = stats.kruskal(*[g[k] for k in ORDER])
        comps = [("WT vs any mutant", g["WT"], mut), ("WT vs truncating", g["WT"], g["Truncating"]),
                 ("WT vs missense/other", g["WT"], g["Missense/other"]), ("Missense vs truncating", g["Missense/other"], g["Truncating"])]
        for name, a, b in comps:
            p = stats.mannwhitneyu(a, b, alternative="two-sided").pvalue
            t = stats.ttest_ind(a, b, equal_var=False).pvalue
            rows.append(dict(dataset=title, comparison=name, n1=len(a), n2=len(b), median1=np.median(a), median2=np.median(b),
                             log2FC_median=np.median(b) - np.median(a), mannwhitney_p=p, welch_t_p=t, cliffs_delta=cliffs(b, a)))
        rows.append(dict(dataset=title, comparison="Kruskal-Wallis (3 groups)", mannwhitney_p=kw.pvalue))
        pa = rows[-5]["mannwhitney_p"]
        ax.text(0.02, 0.98, f"Kruskal–Wallis p = {kw.pvalue:.2g}\nWT vs mutant (MWU) p = {pa:.2g}",
                transform=ax.transAxes, va="top", fontsize=9, color="#52514e", zorder=5,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=2))
    fig.suptitle(f"SMARCA2 {unit} by SMARCA4 mutation status in lung adenocarcinoma", fontsize=13, x=0.01, ha="left")
    fig.text(0.01, 0.005, f"Source: {source}. Two-sided Mann–Whitney U.",
             fontsize=8, color="#52514e")
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    fig.savefig(f"{out}.png", dpi=200)
    res = pd.DataFrame(rows); res.to_csv("stats.csv" if out == "smarca2_by_smarca4_luad" else f"stats_{unit}.csv", index=False)
    pd.set_option("display.width", 200); print(res.to_string(float_format=lambda x: f"{x:.3g}"))


if __name__ == "__main__":
    import sys
    for key in (sys.argv[1:] or ANALYSES):
        run(**ANALYSES[key])
