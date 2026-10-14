"""Overlap of FOCAD homozygous deletion with SWI/SNF loss in TCGA LUAD/LUSC (needs tcga_lung.csv)."""
import pandas as pd, numpy as np
from scipy import stats
from tcga_fetch import post, STUDIES

SWISNF = {"SMARCA4": 6597, "ARID1A": 8289, "ARID1B": 57492, "ARID2": 196528, "PBRM1": 55193, "SMARCB1": 6598}
TRUNC = {"Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins", "Splice_Site", "Nonstop_Mutation", "Translation_Start_Site"}

t = pd.read_csv("tcga_lung.csv").set_index("sample")
t = t[t.sequenced & t.FOCAD_gistic.notna()]
rows = []
for tumor, study in STUDIES.items():
    sub = t[t.tumor_type == tumor].copy()
    muts = post(f"molecular-profiles/{study}_mutations/mutations/fetch?projection=SUMMARY",
                {"entrezGeneIds": list(SWISNF.values()), "sampleListId": f"{study}_all"})
    cna = post(f"molecular-profiles/{study}_gistic/molecular-data/fetch?projection=SUMMARY",
               {"entrezGeneIds": list(SWISNF.values()), "sampleListId": f"{study}_cna"})
    sym = {v: k for k, v in SWISNF.items()}
    trunc = pd.DataFrame([(x["sampleId"], sym[x["entrezGeneId"]]) for x in muts if x["mutationType"] in TRUNC],
                         columns=["sample", "gene"])
    homdel = pd.DataFrame([(x["sampleId"], sym[x["entrezGeneId"]]) for x in cna if x["value"] == -2],
                          columns=["sample", "gene"])
    alt = pd.concat([trunc, homdel])
    for g in SWISNF:
        sub[f"{g}_loss"] = sub.index.isin(alt.loc[alt.gene == g, "sample"])
    sub["any_swisnf_loss"] = sub[[f"{g}_loss" for g in SWISNF]].any(axis=1)
    fd = sub.FOCAD_gistic == -2
    for g in list(SWISNF) + ["any_swisnf"]:
        a = sub[f"{g}_loss"]
        tab = pd.crosstab(fd, a).reindex(index=[False, True], columns=[False, True], fill_value=0)
        orr, p = stats.fisher_exact(tab.values)
        rows.append(dict(cohort=tumor, swisnf=g, n=len(sub), pct_swisnf_loss=100 * a.mean(),
                         pct_focad_del=100 * fd.mean(), both=int((fd & a).sum()),
                         pct_both=100 * (fd & a).mean(), expected_both_if_independent=len(sub) * fd.mean() * a.mean(),
                         odds_ratio=orr, fisher_p=p))
res = pd.DataFrame(rows)
res.round(3).to_csv("swisnf_tcga_overlap.csv", index=False)
pd.set_option("display.width", 220)
print(res.round(2).to_string(index=False))
