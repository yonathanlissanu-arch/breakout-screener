"""SMARCA4 homozygous deletions in DepMap 24Q4 cell lines: which neighbours are co-deleted, confirmed by expression,
and are any of the co-deleted genes' paralogs / the genes themselves dependencies?

Usage: python3 -P depmap_check.py <DEPMAP_DIR>
"""
import sys
import numpy as np, pandas as pd

D = sys.argv[1]
genes = pd.read_csv("genes_chr19.csv")
s4 = genes.loc[genes.gene == "SMARCA4", "start"].iloc[0]
near = genes[(genes.start - s4).abs() < 3e6]

def matrix(fname, keep):
    header = pd.read_csv(f"{D}/{fname}", nrows=0).columns
    pick = {c: c.split(" (")[0] for c in header[1:] if c.split(" (")[0] in keep}
    return pd.read_csv(f"{D}/{fname}", usecols=[header[0]] + list(pick), index_col=header[0]).rename(columns=pick)

model = pd.read_csv(f"{D}/Model.csv", index_col="ModelID")
cn = matrix("OmicsCNGene.csv", set(near.gene))
ex = matrix("OmicsExpressionProteinCodingGenesTPMLogp1.csv", set(near.gene))
order = [g for g in near.gene if g in cn.columns]
hd = cn.index[cn["SMARCA4"] < 0.25]
print("DepMap models with SMARCA4 relative CN < 0.25:", len(hd))
rows = []
for mid in hd:
    x = cn.loc[mid, order]
    i = order.index("SMARCA4"); lo = hi = i
    while lo > 0 and x.iloc[lo - 1] < 0.25: lo -= 1
    while hi < len(order) - 1 and x.iloc[hi + 1] < 0.25: hi += 1
    rows.append(dict(ModelID=mid, cell_line=model.CellLineName.get(mid), lineage=model.OncotreeLineage.get(mid),
                     subtype=model.OncotreeCode.get(mid), n_genes=hi - lo + 1, codeleted=";".join(order[lo:hi + 1]),
                     SMARCA4_expr=ex.loc[mid, "SMARCA4"] if mid in ex.index else np.nan))
ext = pd.DataFrame(rows).sort_values("n_genes")
ext.to_csv("depmap_smarca4_homdel_lines.csv", index=False)
freq = pd.Series({g: (cn.loc[hd, g] < 0.25).mean() for g in order}, name="frac_codeleted")
out = near.set_index("gene").loc[order, ["start"]].join(freq)
out["dist_Mb"] = (out.start - s4) / 1e6
# expression confirmation: median log2TPM in co-deleted vs other lines
for g in order:
    dl = cn.index[(cn[g] < 0.25)].intersection(ex.index)
    out.loc[g, "expr_deleted_median"] = ex.loc[dl, g].median() if len(dl) and g in ex.columns else np.nan
    out.loc[g, "expr_all_median"] = ex[g].median() if g in ex.columns else np.nan
out.round(3).to_csv("depmap_codeletion_frequency.csv")
pd.set_option("display.width", 220)
print(ext.drop(columns=["codeleted"]).to_string(index=False))
print(out[out.frac_codeleted > 0].round(2).to_string())
low = cn["SMARCA4"].nsmallest(12).to_frame("SMARCA4_relcn").join(model[["CellLineName", "OncotreeCode"]]).join(ex[["SMARCA4"]].rename(columns={"SMARCA4": "SMARCA4_expr"}))
print("\nLowest SMARCA4 relative CN:"); print(low.round(3).to_string())
