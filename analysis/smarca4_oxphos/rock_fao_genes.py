"""Supporting table for the ROCK/OXPHOS synergy speculation: ROCK, AMPK, FAO/malonyl-CoA (ACC/CPT1), YAP-axis and
glycolysis genes in SMARCA4-deficient vs WT NSCLC cell lines (DepMap 24Q4). Expression and CRISPR dependency.

Usage: python3 -P rock_fao_genes.py <DEPMAP_DIR>   (needs depmap_nsclc_lines.csv)
"""
import sys
import pandas as pd, numpy as np
from scipy import stats

D = sys.argv[1]
G = ["ROCK1", "ROCK2", "RHOA", "RHOC", "ARHGEF2",                        # Rho/ROCK
     "STK11", "PRKAA1", "PRKAA2", "CAMKK2",                              # AMPK axis
     "ACACA", "ACACB", "CPT1A", "CPT1B", "CPT2", "ACADM", "HADHA", "MLYCD",  # ACC/malonyl-CoA/FAO
     "FASN", "SCD", "SREBF1",                                            # lipogenesis
     "YAP1", "WWTR1", "AMOTL2", "MYL9", "MYH9", "CFL1",                  # ROCK-actomyosin-YAP
     "SLC2A1", "HK2", "ALDOC", "ESRRA", "PPARGC1A"]                      # glycolysis / mito-biogenesis
lines = pd.read_csv("depmap_nsclc_lines.csv", index_col=0)
lines = lines[lines.group != "excluded"]; dm = lines.group == "SMARCA4-deficient"

def load(fn):
    h = pd.read_csv(f"{D}/{fn}", nrows=0).columns
    c = [x for x in h if x.split(" (")[0] in G]
    e = pd.read_csv(f"{D}/{fn}", usecols=[h[0]] + c, index_col=0); e.columns = [x.split(" (")[0] for x in e.columns]
    return e.reindex(lines.index)

def tab(mat, kind):
    rows = []
    for g in G:
        if g not in mat.columns: continue
        a, b = mat.loc[dm, g].dropna(), mat.loc[~dm, g].dropna()
        if len(a) > 3 and len(b) > 3:
            rows.append(dict(gene=g, kind=kind, mean_deficient=a.mean(), mean_wt=b.mean(),
                             diff=a.mean() - b.mean(), mwu_p=stats.mannwhitneyu(a, b).pvalue))
    return pd.DataFrame(rows)

res = pd.concat([tab(load("OmicsExpressionProteinCodingGenesTPMLogp1.csv"), "expression_log2TPM"),
                 tab(load("CRISPRGeneEffect.csv"), "crispr_gene_effect")])
res.to_csv("rock_fao_supporting_genes.csv", index=False)
pd.set_option("display.width", 200)
print(res.round(3).to_string(index=False))
