"""Validate the SMARCA4-deficiency glycolytic-expression signature in TCGA LUAD tumors (cBioPortal).

SMARCA4-deficient tumor: truncating SMARCA4 mutation, or SMARCA4 mRNA z <= -2 (vs all tumors). WT: no mutation and z >= -0.5.
Compares mRNA (RSEM z-scores) of glycolysis / HIF / metabolic genes between groups; also adjusts for STK11/KEAP1.
"""
import json, urllib.request
import numpy as np, pandas as pd
from scipy import stats
import statsmodels.formula.api as smf
from gene_sets import GENE_SETS, oxphos_genes

API = "https://www.cbioportal.org/api"; STUDY = "luad_tcga_pan_can_atlas_2018"
TRUNC = {"Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins", "Splice_Site", "Nonstop_Mutation", "Translation_Start_Site"}

def get(p): return json.load(urllib.request.urlopen(f"{API}/{p}"))
def post(p, b):
    r = urllib.request.Request(f"{API}/{p}", data=json.dumps(b).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=300))

KEY = ["ALDOC", "ENO2", "SLC2A1", "HK2", "PFKM", "PFKP", "ALDOA", "PKM", "LDHA", "ENO1", "GAPDH", "PGK1",
       "FBP1", "MPC1", "MPC2", "HIF1A", "VEGFA", "CA9", "ESRRA", "PPARGC1A", "SLC16A3", "GLS", "HK1"]
genes = {g["hugoGeneSymbol"]: g["entrezGeneId"] for g in post("genes/fetch?geneIdType=HUGO_GENE_SYMBOL", KEY + ["SMARCA4", "STK11", "KEAP1"])}

def zmatrix(entrez):
    d = post(f"molecular-profiles/{STUDY}_rna_seq_v2_mrna_median_all_sample_Zscores/molecular-data/fetch?projection=SUMMARY",
             {"entrezGeneIds": entrez, "sampleListId": f"{STUDY}_all"})
    sym = {v: k for k, v in genes.items()}
    return (pd.DataFrame([{"sample": x["sampleId"], "gene": sym[x["entrezGeneId"]], "z": x["value"]} for x in d])
            .pivot(index="sample", columns="gene", values="z"))

z = zmatrix(list(genes.values()))
mu = post(f"molecular-profiles/{STUDY}_mutations/mutations/fetch?projection=SUMMARY",
          {"entrezGeneIds": [genes[g] for g in ["SMARCA4", "STK11", "KEAP1"]], "sampleListId": f"{STUDY}_all"})
sym = {v: k for k, v in genes.items()}
trunc_s4 = {x["sampleId"] for x in mu if x["entrezGeneId"] == genes["SMARCA4"] and x["mutationType"] in TRUNC}
for g in ["STK11", "KEAP1"]:
    z[f"{g}_mut"] = z.index.isin({x["sampleId"] for x in mu if x["entrezGeneId"] == genes[g]}).astype(int)
z["deficient"] = (z.index.isin(trunc_s4) | (z["SMARCA4"] <= -2)).astype(int)
z["wt"] = ((~z.index.isin({x["sampleId"] for x in mu if x["entrezGeneId"] == genes["SMARCA4"]})) & (z["SMARCA4"] >= -0.5)).astype(int)
z.to_csv("tcga_luad_signature.csv")

sub = z[(z.deficient == 1) | (z.wt == 1)].copy()
rows = []
for g in KEY:
    a, b = z.loc[z.deficient == 1, g].dropna(), z.loc[z.wt == 1, g].dropna()
    fit = smf.ols(f"Q('{g}') ~ deficient + STK11_mut + KEAP1_mut", data=sub).fit()
    rows.append(dict(gene=g, mean_deficient=a.mean(), mean_wt=b.mean(), diff=a.mean() - b.mean(),
                     mwu_p=stats.mannwhitneyu(a, b).pvalue, adj_coef=fit.params["deficient"], adj_p=fit.pvalues["deficient"]))
res = pd.DataFrame(rows).sort_values("diff")
res.to_csv("tcga_luad_gene_stats.csv", index=False)
pd.set_option("display.width", 200)
print(f"TCGA LUAD: {int(z.deficient.sum())} SMARCA4-deficient (trunc or z<=-2), {int(z.wt.sum())} WT")
print(res.round(3).to_string(index=False))
# glycolysis score
gly = [g for g in GENE_SETS["Glycolysis (core enzymes)"] + GENE_SETS["Glucose uptake (GLUTs)"] if g in z.columns]
z["glyscore"] = z[gly].mean(axis=1)
a, b = z.loc[z.deficient == 1, "glyscore"].dropna(), z.loc[z.wt == 1, "glyscore"].dropna()
print(f"\nGlycolysis score: deficient {a.mean():.2f} vs WT {b.mean():.2f}, MWU p={stats.mannwhitneyu(a,b).pvalue:.2g}")
