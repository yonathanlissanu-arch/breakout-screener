"""Per-gene co-deletion frequency among credible (focal, <= 2 Mb) SMARCA4 homozygous deletions in TCGA."""
import pandas as pd
genes = pd.read_csv("genes_chr19.csv").set_index("gene")
ext = pd.read_csv("homdel_extents.csv")
z = pd.read_csv("homdel_expression_check.csv", index_col=0)["SMARCA4"]
ext["SMARCA4_mrna_z"] = ext["sample"].map(z)
focal = ext[ext.size_Mb <= 2]
conf = focal[focal.SMARCA4_mrna_z <= -2]
rows = []
for g in genes.index:
    a = focal.codeleted.str.split(";").apply(lambda x: g in x).sum()
    b = conf.codeleted.str.split(";").apply(lambda x: g in x).sum()
    if a: rows.append(dict(gene=g, dist_from_SMARCA4_Mb=round((genes.loc[g, "start"] - genes.loc["SMARCA4", "start"]) / 1e6, 3),
                           focal_events=a, pct_focal=round(100 * a / len(focal), 1),
                           confirmed_events=b, pct_confirmed=round(100 * b / len(conf), 1)))
out = pd.DataFrame(rows).sort_values("dist_from_SMARCA4_Mb")
out.to_csv("codeletion_frequency_focal.csv", index=False)
ext.to_csv("homdel_extents.csv", index=False)
print(f"focal events: {len(focal)}, mRNA-confirmed: {len(conf)}")
print(out[out.pct_focal >= 15].to_string(index=False))
