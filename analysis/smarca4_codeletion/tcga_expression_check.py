"""Check TCGA SMARCA4 homozygous-deletion calls against mRNA: expression z-scores (vs all tumors in the same study)
for SMARCA4, its nearest neighbours, and common-essential genes inside the larger deleted segments."""
import pandas as pd, numpy as np
from tcga_fetch import post

CHECK = ["SMARCA4", "TIMM29", "YIPF2", "CARM1", "LDLR", "SPC24", "TMED1", "DNM2", "ILF3", "KEAP1", "CDC37", "EIF3G", "DNMT1", "PIN1"]
genes = pd.read_csv("genes_chr19.csv").set_index("gene")
ext = pd.read_csv("homdel_extents.csv")
rows = []
for st, g in ext.groupby("study_id"):
    prof = f"{st}_rna_seq_v2_mrna_median_all_sample_Zscores"
    try:
        d = post(f"molecular-profiles/{prof}/molecular-data/fetch?projection=SUMMARY",
                 {"entrezGeneIds": [int(genes.loc[x, "entrez"]) for x in CHECK], "sampleIds": g["sample"].tolist()})
    except Exception as e:
        print("no mRNA for", st, e); continue
    sym = {int(genes.loc[x, "entrez"]): x for x in CHECK}
    rows += [{"sample": x["sampleId"], "gene": sym[x["entrezGeneId"]], "z": x["value"]} for x in d]
z = pd.DataFrame(rows).pivot(index="sample", columns="gene", values="z")[CHECK]
out = ext.set_index("sample")[["study", "n_genes", "size_Mb", "left", "right"]].join(z).sort_values("n_genes")
out.round(2).to_csv("homdel_expression_check.csv")
pd.set_option("display.width", 250)
print(out.round(1).to_string())
