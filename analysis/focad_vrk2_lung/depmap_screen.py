"""Genome-wide CRISPR dependency comparisons for FOCAD-deleted and VRK2-low cell lines (DepMap 24Q4).

Usage: python3 -P depmap_screen.py <DEPMAP_DIR>   (needs depmap_models.csv from depmap_build.py)

Groups (models with CRISPR data):
  FOCAD-deleted : FOCAD relative CN < 0.25 and FOCAD log2(TPM+1) < 1 (homozygous loss, confirmed by expression)
  FOCAD-intact  : FOCAD relative CN >= 0.5
  9p21-matched control : FOCAD-intact lines that still have MTAP homozygously deleted (relative CN < 0.25)
  VRK2-low      : VRK2 log2(TPM+1) < 2; VRK2-normal: >= 3
"""
import sys
import numpy as np, pandas as pd
from scipy import stats

def bh(p):
    p = np.asarray(p); n = len(p); o = np.argsort(p)
    q = np.empty(n); q[o] = np.minimum.accumulate((p[o] * n / np.arange(1, n + 1))[::-1])[::-1]
    return np.minimum(q, 1)

def compare(ge, a, b, label):
    A, B = ge.loc[a], ge.loc[b]
    t, p = stats.ttest_ind(A, B, equal_var=False, nan_policy="omit")
    res = pd.DataFrame({"gene": ge.columns, "mean_test": A.mean().values, "mean_control": B.mean().values,
                        "diff": (A.mean() - B.mean()).values, "t": t, "p": p,
                        "n_test": A.notna().sum().values, "n_control": B.notna().sum().values})
    res = res.dropna(subset=["p"])
    res["fdr"] = bh(res["p"])
    res.insert(0, "comparison", label)
    return res.sort_values("t")

if __name__ == "__main__":
    D = sys.argv[1]
    ge = pd.read_csv(f"{D}/CRISPRGeneEffect.csv", index_col=0)
    ge.columns = [c.split(" (")[0] for c in ge.columns]
    m = pd.read_csv("depmap_models.csv", index_col=0).loc[ge.index]
    msi = pd.read_csv(f"{D}/OmicsSignatures.csv", index_col=0)["MSIScore"]
    m["MSIScore"] = msi
    m["MSI_high"] = m["MSIScore"] >= 20  # MSIsensor2 score

    focad_del = m.index[(m.FOCAD_relcn < 0.25) & (m.FOCAD_expr < 1)]
    focad_intact = m.index[m.FOCAD_relcn >= 0.5]
    mtap_only = m.index[(m.FOCAD_relcn >= 0.5) & (m.MTAP_relcn < 0.25)]
    vrk2_low = m.index[m.VRK2_expr < 2]
    vrk2_norm = m.index[m.VRK2_expr >= 3]
    m["FOCAD_group"] = np.where(m.index.isin(focad_del), "FOCAD-deleted",
                         np.where(m.index.isin(mtap_only), "MTAP-del, FOCAD-intact",
                         np.where(m.index.isin(focad_intact), "FOCAD-intact", "ambiguous")))
    m["VRK2_group"] = np.where(m.index.isin(vrk2_low), "VRK2-low",
                        np.where(m.index.isin(vrk2_norm), "VRK2-normal", "ambiguous/NA"))

    res = pd.concat([
        compare(ge, focad_del, focad_intact, "FOCAD-del vs FOCAD-intact (pan-cancer)"),
        compare(ge, focad_del, mtap_only, "FOCAD-del vs MTAP-del/FOCAD-intact (pan-cancer)"),
        compare(ge, vrk2_low, vrk2_norm, "VRK2-low vs VRK2-normal (pan-cancer)"),
    ])
    res.to_csv("depmap_dependency_screen.csv", index=False)

    # continuous biomarker: correlation of each gene's effect with FOCAD / VRK2 expression
    cors = []
    for g in ["FOCAD", "VRK2"]:
        x = m[f"{g}_expr"].dropna(); X = ge.loc[x.index]
        r = X.apply(lambda col: col.corr(x))
        cors.append(pd.DataFrame({"biomarker": f"{g} expression", "gene": r.index, "pearson_r": r.values})
                    .sort_values("pearson_r", ascending=False))
    pd.concat(cors).to_csv("depmap_expression_correlations.csv", index=False)

    keep = ["PELO", "HBS1L", "VRK1", "FOCAD", "VRK2", "MTAP", "PRMT5", "MAT2A"]
    m.join(ge[[g for g in keep if g in ge.columns]].add_suffix("_effect")).to_csv("depmap_crispr_models.csv")

    pd.set_option("display.width", 220)
    print({k: len(v) for k, v in dict(focad_del=focad_del, intact=focad_intact, mtap_only=mtap_only,
                                       vrk2_low=vrk2_low, vrk2_norm=vrk2_norm).items()})
    for c in res.comparison.unique():
        print("\n==", c); print(res[res.comparison == c].head(15).round(4).to_string(index=False))
    for c in cors:
        print("\n==", c.biomarker.iloc[0], "most positive r (lower expression -> more dependent)")
        print(c.head(10).round(3).to_string(index=False))
