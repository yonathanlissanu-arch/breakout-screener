"""Are the metabolic expression differences due to SMARCA4 itself, or to co-occurring STK11 / KEAP1 loss and subtype?
Gene-set scores (mean z of member genes) and key genes regressed on SMARCA4 status + STK11 + KEAP1 + subtype.

Usage: python3 -P depmap_adjusted.py <DEPMAP_DIR>   (needs depmap_nsclc_lines.csv from depmap_analysis.py)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import statsmodels.formula.api as smf
from gene_sets import GENE_SETS, oxphos_genes

D = sys.argv[1]
lines = pd.read_csv("depmap_nsclc_lines.csv", index_col=0)
lines = lines[lines.group != "excluded"].copy()
lines["s4def"] = (lines.group == "SMARCA4-deficient").astype(int)
lines["subtype"] = np.where(lines.OncotreeCode == "LUAD", "LUAD", np.where(lines.OncotreeCode == "LUSC", "LUSC", "other"))
mu = pd.read_csv(f"{D}/OmicsSomaticMutations.csv", usecols=["ModelID", "HugoSymbol", "LikelyLoF", "VariantInfo"])
for g in ["STK11", "KEAP1"]:
    x = mu[(mu.HugoSymbol == g) & ((mu.LikelyLoF == True) | mu.VariantInfo.str.contains("missense", na=False))]
    lines[f"{g}_mut"] = lines.index.isin(set(x.ModelID)).astype(int)
cn_header = pd.read_csv(f"{D}/OmicsCNGene.csv", nrows=0).columns
cn = pd.read_csv(f"{D}/OmicsCNGene.csv", usecols=[cn_header[0]] + [c for c in cn_header if c.startswith("STK11 (")], index_col=0)
lines.loc[lines.index.intersection(cn.index), "STK11_mut"] |= (cn.loc[lines.index.intersection(cn.index)].iloc[:, 0] < 0.25).astype(int)

expr = pd.read_csv(f"{D}/OmicsExpressionProteinCodingGenesTPMLogp1.csv", index_col=0)
expr.columns = [c.split(" (")[0] for c in expr.columns]
expr = expr.loc[lines.index]
z = (expr - expr.mean()) / expr.std()
sets = dict(GENE_SETS); sets["OXPHOS (all nuclear subunits)"] = oxphos_genes(expr.columns)
for name, genes in sets.items():
    g = [x for x in genes if x in z.columns and expr[x].mean() > 1]
    lines[f"score::{name}"] = z[g].mean(axis=1)
KEY = ["ALDOC", "ENO2", "SLC2A1", "HK2", "PFKM", "FBP1", "MPC1", "HIF1A", "VEGFA", "ESRRA", "PPARGC1A", "LDHA", "PKM"]
for g in KEY: lines[f"gene::{g}"] = expr[g]
lines.to_csv("depmap_nsclc_lines_scored.csv")

print("co-occurrence:", pd.crosstab(lines.s4def, [lines.STK11_mut, lines.KEAP1_mut]).to_dict())
rows = []
for col in [c for c in lines.columns if c.startswith(("score::", "gene::"))]:
    d = lines.rename(columns={col: "y"})
    for label, f in [("unadjusted", "y ~ s4def"), ("adj STK11+KEAP1+subtype", "y ~ s4def + STK11_mut + KEAP1_mut + C(subtype)")]:
        fit = smf.ols(f, data=d).fit()
        rows.append(dict(feature=col, model=label, SMARCA4_def_coef=fit.params["s4def"], p=fit.pvalues["s4def"],
                         STK11_coef=fit.params.get("STK11_mut", np.nan), STK11_p=fit.pvalues.get("STK11_mut", np.nan),
                         KEAP1_coef=fit.params.get("KEAP1_mut", np.nan), KEAP1_p=fit.pvalues.get("KEAP1_mut", np.nan), n=int(fit.nobs)))
res = pd.DataFrame(rows)
res.to_csv("depmap_adjusted_models.csv", index=False)
pd.set_option("display.width", 230)
un = res[res.model == "unadjusted"].set_index("feature")[["SMARCA4_def_coef", "p"]].add_prefix("unadj_")
adj = res[res.model != "unadjusted"].set_index("feature")[["SMARCA4_def_coef", "p", "STK11_coef", "STK11_p", "KEAP1_coef", "KEAP1_p"]].add_prefix("adj_")
print(un.join(adj).sort_values("adj_p").to_string(float_format=lambda x: f"{x:.3g}"))
