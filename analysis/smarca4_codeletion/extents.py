"""Per-tumor extent of each SMARCA4 homozygous deletion: the contiguous run of GISTIC -2 genes containing SMARCA4."""
import pandas as pd
g = pd.read_csv("genes_chr19.csv")
h = pd.read_csv("pancan_homdel_region.csv").merge(g, on="entrez")
ext = []
for smp, x in h.sort_values("start").groupby("sample"):
    x = x.reset_index(drop=True); i = x.index[x.gene == "SMARCA4"][0]; lo = hi = i
    while lo > 0 and x.gistic[lo - 1] == -2: lo -= 1
    while hi < len(x) - 1 and x.gistic[hi + 1] == -2: hi += 1
    ext.append(dict(sample=smp, study_id=x.study[0], study=x.study[0].split("_")[0].upper(), n_genes=hi - lo + 1,
                    left=x.gene[lo], right=x.gene[hi], size_Mb=round((x.end[hi] - x.start[lo]) / 1e6, 2),
                    codeleted=";".join(x.gene[lo:hi + 1]), SMARCA4_log2cn=x.loc[i, "log2cn"]))
pd.DataFrame(ext).sort_values("n_genes").to_csv("homdel_extents.csv", index=False)
