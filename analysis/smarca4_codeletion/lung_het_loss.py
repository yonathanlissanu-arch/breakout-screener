"""Lung (TCGA LUAD/LUSC): single-copy loss around SMARCA4, and whether SMARCA4-mutant tumors carry 19p loss that
also takes one copy of KEAP1 and other neighbours. Uses lung_region_gistic.csv + pancan_smarca4_status.csv."""
import numpy as np, pandas as pd
from scipy import stats
from tcga_fetch import post

genes = pd.read_csv("genes_chr19.csv")
g = pd.read_csv("lung_region_gistic.csv").merge(genes[["gene", "entrez", "start"]], on="entrez")
g["tumor"] = g.study.str[:4].str.upper()
wide = g.pivot_table(index=["sample", "tumor"], columns="gene", values="gistic").reset_index()
st = pd.read_csv("pancan_smarca4_status.csv")
wide = wide.merge(st[["sample", "SMARCA4_truncating"]], on="sample", how="left")
# KEAP1 mutations (any non-silent)
km = []
for s in ["luad_tcga_pan_can_atlas_2018", "lusc_tcga_pan_can_atlas_2018"]:
    km += [x["sampleId"] for x in post(f"molecular-profiles/{s}_mutations/mutations/fetch?projection=SUMMARY",
                                       {"entrezGeneIds": [9817], "sampleListId": f"{s}_all"})]
wide["KEAP1_mut"] = wide["sample"].isin(set(km))

s4 = genes.loc[genes.gene == "SMARCA4", "start"].iloc[0]
near = genes[(genes.start - s4).abs() < 1.5e6].sort_values("start").gene
near = [x for x in near if x in wide.columns]
rows = []
for t, w in wide.groupby("tumor"):
    s4loss = w.SMARCA4 <= -1
    for x in near:
        rows.append(dict(tumor=t, gene=x, dist_Mb=(genes.set_index("gene").loc[x, "start"] - s4) / 1e6,
                         pct_loss_all=100 * (w[x] <= -1).mean(),
                         pct_loss_given_SMARCA4_loss=100 * (w.loc[s4loss, x] <= -1).mean()))
prof = pd.DataFrame(rows)
prof.round(2).to_csv("lung_single_copy_loss_profile.csv", index=False)

summ = []
for t, w in wide.groupby("tumor"):
    mut = w.SMARCA4_truncating == True
    summ.append(dict(tumor=t, n=len(w), SMARCA4_truncating=int(mut.sum()),
                     pct_SMARCA4_loss_all=100 * (w.SMARCA4 <= -1).mean(),
                     pct_SMARCA4_loss_in_truncating=100 * (w.loc[mut, "SMARCA4"] <= -1).mean(),
                     pct_KEAP1_loss_in_truncating=100 * (w.loc[mut, "KEAP1"] <= -1).mean(),
                     pct_KEAP1_mut_in_truncating=100 * w.loc[mut, "KEAP1_mut"].mean(),
                     pct_KEAP1_mut_in_rest=100 * w.loc[~mut, "KEAP1_mut"].mean(),
                     fisher_p_KEAP1mut=stats.fisher_exact(pd.crosstab(mut, w.KEAP1_mut).values)[1],
                     pct_KEAP1_loss_given_SMARCA4_loss=100 * (w.loc[w.SMARCA4 <= -1, "KEAP1"] <= -1).mean()))
summ = pd.DataFrame(summ)
summ.round(3).to_csv("lung_smarca4_keap1_summary.csv", index=False)
pd.set_option("display.width", 220)
print(summ.round(2).to_string(index=False))
print(prof[prof.gene.isin(["KEAP1", "DNM2", "CARM1", "YIPF2", "TIMM29", "SMARCA4", "LDLR", "CDC37", "ILF3", "EIF3G", "PIN1", "DNMT1"])]
      .pivot(index=["gene", "dist_Mb"], columns="tumor", values="pct_loss_given_SMARCA4_loss").sort_index(level=1).round(1))
