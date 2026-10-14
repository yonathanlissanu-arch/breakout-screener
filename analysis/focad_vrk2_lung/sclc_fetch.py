"""VRK2 / VRK1 / FOCAD expression in SCLC tumors (U Cologne, George et al. Nature 2015; cBioPortal)."""
import pandas as pd
from tcga_fetch import post, GENES

STUDY = "sclc_ucologne_2015"
if __name__ == "__main__":
    d = post(f"molecular-profiles/{STUDY}_rna_seq_mrna/molecular-data/fetch?projection=SUMMARY",
             {"entrezGeneIds": [GENES[g] for g in ["VRK2", "VRK1", "FOCAD", "MTAP"]], "sampleListId": f"{STUDY}_all"})
    sym = {v: k for k, v in GENES.items()}
    df = (pd.DataFrame([{"sample": x["sampleId"], "gene": sym[x["entrezGeneId"]], "v": x["value"]} for x in d])
          .pivot(index="sample", columns="gene", values="v"))
    df.to_csv("sclc_ucologne_expression.csv")
    print(df.describe().round(2)); print(df.sort_values("VRK2").head(12).round(2))
