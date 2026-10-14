"""SMARCA4-deficient vs SMARCA4-WT NSCLC cell lines (DepMap 24Q4): genome-wide expression differences,
metabolic gene-set shifts, and CRISPR dependency on OXPHOS / glycolysis genes.

Usage: python3 -P depmap_analysis.py <DEPMAP_DIR>
SMARCA4-deficient: LikelyLoF SMARCA4 mutation, or SMARCA4 log2(TPM+1) < 3.
SMARCA4-WT: no SMARCA4 mutation and SMARCA4 log2(TPM+1) >= 5.
"""
import sys
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from gene_sets import GENE_SETS, oxphos_genes

def bh(p):
    p = np.asarray(p); n = len(p); o = np.argsort(p)
    q = np.empty(n); q[o] = np.minimum.accumulate((p[o] * n / np.arange(1, n + 1))[::-1])[::-1]
    return np.minimum(q, 1)

def load(path):
    df = pd.read_csv(path, index_col=0)
    df.columns = [c.split(" (")[0] for c in df.columns]
    return df

def compare(mat, a, b):
    A, B = mat.loc[mat.index.intersection(a)], mat.loc[mat.index.intersection(b)]
    t, p = stats.ttest_ind(A, B, equal_var=False, nan_policy="omit")
    r = pd.DataFrame({"gene": mat.columns, "mean_deficient": A.mean().values, "mean_wt": B.mean().values,
                      "diff": (A.mean() - B.mean()).values, "t": t, "p": p}).dropna(subset=["p"])
    r["fdr"] = bh(r.p)
    return r.set_index("gene"), len(A), len(B)

def set_tests(res, sets, stat="t"):
    rows = []
    for name, genes in sets.items():
        g = [x for x in genes if x in res.index]
        if len(g) < 3: continue
        inset, rest = res.loc[g, stat], res.loc[~res.index.isin(g), stat]
        rows.append(dict(gene_set=name, n_genes=len(g), mean_t=inset.mean(), median_diff=res.loc[g, "diff"].median(),
                         n_up_fdr10=int(((res.loc[g, "fdr"] < 0.1) & (res.loc[g, "diff"] > 0)).sum()),
                         n_down_fdr10=int(((res.loc[g, "fdr"] < 0.1) & (res.loc[g, "diff"] < 0)).sum()),
                         p_vs_all_genes=stats.mannwhitneyu(inset, rest).pvalue))
    return pd.DataFrame(rows).sort_values("mean_t")

if __name__ == "__main__":
    D = sys.argv[1]
    model = pd.read_csv(f"{D}/Model.csv", index_col="ModelID")
    ns = model[(model.OncotreeLineage == "Lung") &
               model.OncotreePrimaryDisease.isin(["Non-Small Cell Lung Cancer", "SMARCA4-deficient undifferentiated tumor"])]
    expr = load(f"{D}/OmicsExpressionProteinCodingGenesTPMLogp1.csv").loc[lambda d: d.index.isin(ns.index)]
    mu = pd.read_csv(f"{D}/OmicsSomaticMutations.csv", usecols=["ModelID", "HugoSymbol", "LikelyLoF", "ProteinChange"])
    s4 = mu[mu.HugoSymbol == "SMARCA4"]
    lof, anymut = set(s4.loc[s4.LikelyLoF == True, "ModelID"]), set(s4.ModelID)
    sm = expr["SMARCA4"]
    deficient = sm.index[sm.index.isin(lof) | (sm < 3)]
    wt = sm.index[~sm.index.isin(anymut) & (sm >= 5)]
    lines = ns.loc[expr.index, ["CellLineName", "OncotreeCode"]].assign(
        SMARCA4_expr=sm, SMARCA4_mutation=lambda d: d.index.map(s4.groupby("ModelID").ProteinChange.agg(lambda x: "; ".join(map(str, x)))),
        group=lambda d: np.where(d.index.isin(deficient), "SMARCA4-deficient", np.where(d.index.isin(wt), "SMARCA4-WT", "excluded")))
    lines.sort_values(["group", "CellLineName"]).to_csv("depmap_nsclc_lines.csv")

    expressed = expr.columns[(expr > 1).mean() > 0.2]
    de, na, nb = compare(expr[expressed], deficient, wt)
    de.sort_values("t").to_csv("depmap_expression_de.csv")
    sets = dict(GENE_SETS); sets["OXPHOS (all nuclear subunits)"] = oxphos_genes(expr.columns)
    st = set_tests(de, sets); st.to_csv("depmap_expression_gene_sets.csv", index=False)

    ge = load(f"{D}/CRISPRGeneEffect.csv").loc[lambda d: d.index.isin(ns.index)]
    dep, ca, cb = compare(ge, deficient, wt)
    dep.sort_values("t").to_csv("depmap_crispr_de.csv")
    dst = set_tests(dep, sets); dst.to_csv("depmap_crispr_gene_sets.csv", index=False)

    pd.set_option("display.width", 220)
    print(f"expression: {na} deficient vs {nb} WT; CRISPR: {ca} vs {cb}")
    print("\n== expression gene sets (t>0 = higher in SMARCA4-deficient)"); print(st.round(3).to_string(index=False))
    print("\n== CRISPR gene sets (t<0 = more essential in SMARCA4-deficient)"); print(dst.round(3).to_string(index=False))
    focus = [g for gs in GENE_SETS.values() for g in gs]
    print("\n== glycolysis / related genes, expression"); print(de.loc[de.index.intersection(focus)].sort_values("t").round(3).head(25).to_string())
    print("\n== top CRISPR dependencies in deficient lines"); print(dep.sort_values("t").head(20).round(3).to_string())
