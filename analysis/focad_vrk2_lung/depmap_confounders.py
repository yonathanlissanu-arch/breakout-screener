"""Check FOCAD->PELO/HBS1L and VRK2->VRK1 for confounding by MSI and lineage; then look at lung lines.

Usage: python3 -P depmap_confounders.py   (needs depmap_crispr_models.csv from depmap_screen.py)
"""
import numpy as np, pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

m = pd.read_csv("depmap_crispr_models.csv", index_col=0)
m["lineage"] = m["OncotreeLineage"].fillna("Other")
rows = []

def ols(formula, data, term, label):
    fit = smf.ols(formula, data=data).fit()
    rows.append(dict(test=label, coef=fit.params[term], p=fit.pvalues[term], n=int(fit.nobs)))

# FOCAD: deleted vs intact (incl. MTAP-only), adjusted for lineage and MSI; and MSS-only
f = m[m.FOCAD_group.isin(["FOCAD-deleted", "FOCAD-intact", "MTAP-del, FOCAD-intact"])].copy()
f["focad_del"] = (f.FOCAD_group == "FOCAD-deleted").astype(int)
f["mtap_del"] = (f.MTAP_relcn < 0.25).astype(int)
for g in ["PELO", "HBS1L"]:
    ols(f"{g}_effect ~ focad_del", f, "focad_del", f"{g}: FOCAD-del, unadjusted")
    ols(f"{g}_effect ~ focad_del + mtap_del + MSI_high + C(lineage)", f, "focad_del",
        f"{g}: FOCAD-del, adjusted for MTAP-del + MSI + lineage")
    ols(f"{g}_effect ~ focad_del + mtap_del + C(lineage)", f[~f.MSI_high], "focad_del",
        f"{g}: FOCAD-del, MSS lines only, adjusted for MTAP-del + lineage")
    ols(f"{g}_effect ~ MSI_high + C(lineage)", f[f.focad_del == 0], "MSI_high[T.True]",
        f"{g}: MSI-high (FOCAD-intact lines), lineage-adjusted [reference]")

# VRK2: continuous expression and low vs normal, adjusted for lineage; and outside CNS/PNS
v = m[m.VRK2_group.isin(["VRK2-low", "VRK2-normal"])].copy()
v["vrk2_low"] = (v.VRK2_group == "VRK2-low").astype(int)
ols("VRK1_effect ~ vrk2_low", v, "vrk2_low", "VRK1: VRK2-low, unadjusted")
ols("VRK1_effect ~ vrk2_low + C(lineage)", v, "vrk2_low", "VRK1: VRK2-low, lineage-adjusted")
nn = v[~v.lineage.isin(["CNS/Brain", "Peripheral Nervous System"])]
ols("VRK1_effect ~ vrk2_low + C(lineage)", nn, "vrk2_low", "VRK1: VRK2-low, excluding CNS/PNS lines, lineage-adjusted")
ols("VRK1_effect ~ VRK2_expr + C(lineage)", m.dropna(subset=["VRK2_expr"]), "VRK2_expr",
    "VRK1: per log2(TPM+1) VRK2, lineage-adjusted")

res = pd.DataFrame(rows)
res.to_csv("depmap_confounder_checks.csv", index=False)
pd.set_option("display.width", 200)
print(res.to_string(index=False, float_format=lambda x: f"{x:.3g}"))

# Lung lines
lung = m[m.lineage == "Lung"]
print("\nLung lines with CRISPR:", len(lung))
print(lung.FOCAD_group.value_counts().to_dict(), lung.VRK2_group.value_counts().to_dict())
cols = ["CellLineName", "OncotreeCode", "FOCAD_relcn", "FOCAD_expr", "MTAP_relcn", "MSIScore", "PELO_effect", "HBS1L_effect"]
print(lung[lung.FOCAD_group == "FOCAD-deleted"][cols].round(2).to_string())
for g in ["PELO", "HBS1L"]:
    a = lung.loc[lung.FOCAD_group == "FOCAD-deleted", f"{g}_effect"]; b = lung.loc[lung.FOCAD_group != "FOCAD-deleted", f"{g}_effect"]
    pct = [(b < x).mean() * 100 for x in a]
    print(f"{g}: lung FOCAD-del {a.round(2).tolist()} vs other lung median {b.median():.2f}; "
          f"% of other lung lines more dependent: {np.round(pct,1).tolist()}; MWU p={stats.mannwhitneyu(a,b).pvalue:.3g}")
print(lung[lung.VRK2_group == "VRK2-low"][["CellLineName", "OncotreeCode", "VRK2_expr", "VRK2_relcn", "VRK1_effect"]].round(2).to_string())
a = lung.loc[lung.VRK2_group == "VRK2-low", "VRK1_effect"]; b = lung.loc[lung.VRK2_group == "VRK2-normal", "VRK1_effect"]
print(f"VRK1 lung: VRK2-low {a.round(2).tolist()} vs VRK2-normal median {b.median():.2f}, MWU p={stats.mannwhitneyu(a,b).pvalue:.3g}")
r = stats.spearmanr(lung.VRK2_expr, lung.VRK1_effect, nan_policy="omit"); print(f"lung Spearman VRK2 expr vs VRK1 effect rho={r.statistic:.2f} p={r.pvalue:.2g}")
