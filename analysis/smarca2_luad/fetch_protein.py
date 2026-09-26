"""Fetch SMARCA2/SMARCA4 protein (mass spec) + SMARCA4 mutations.

Tumors: CPTAC LUAD (Gillette et al., Cell 2020), UMich proteomics via the `cptac` package
        (cBioPortal's copy of this study drops SMARCA2/SMARCA4 from the protein matrix).
Cell lines: CCLE proteomics (Nusinow et al., Cell 2020) via cBioPortal, OncoTree LUAD lines.
"""
import warnings
import pandas as pd
from fetch import get, post, SMARCA2, SMARCA4, TRUNC
warnings.filterwarnings("ignore")

NONCODING = {"Silent", "Intron", "3'UTR", "5'UTR", "3'Flank", "5'Flank", "IGR", "RNA", "lincRNA"}

def classify(types):
    types = set(types) - NONCODING
    if not types: return "WT"
    return "Truncating" if types & TRUNC else "Missense/other"

def fetch_cptac():
    import cptac
    luad = cptac.Luad()
    prot = luad.get_proteomics("umich")
    prot = prot[~prot.index.str.endswith(".N")]  # tumors only
    def gene(g):  # average isoforms if more than one
        return prot.loc[:, [c for c in prot.columns if c[0] == g]].mean(axis=1)
    df = pd.DataFrame({"smarca2_protein": gene("SMARCA2"), "smarca4_protein": gene("SMARCA4")})
    muts = luad.get_somatic_mutation("harmonized")
    sequenced = set(muts.index)
    s4 = muts[muts["Gene"] == "SMARCA4"]
    s4[["Mutation", "Location"]].to_csv("cptac_luad_smarca4_mutations.csv")
    df = df[df.index.isin(sequenced)].dropna(subset=["smarca2_protein"])
    df["smarca4"] = [classify(s4.loc[[s], "Mutation"]) if s in s4.index else "WT" for s in df.index]
    return df.rename_axis("sample").reset_index()

def fetch_ccle():
    study = "ccle_broad_2019"
    samples = get(f"studies/{study}/samples?projection=SUMMARY&pageSize=10000")
    cd = post(f"studies/{study}/clinical-data/fetch?clinicalDataType=SAMPLE",
              {"attributeIds": ["ONCOTREE_CODE"], "ids": [s["sampleId"] for s in samples]})
    luad_lines = {d["sampleId"] for d in cd if d["value"] == "LUAD"}
    sequenced = set(get(f"sample-lists/{study}_sequenced")["sampleIds"])
    expr = post(f"molecular-profiles/{study}_protein_quantification/molecular-data/fetch?projection=SUMMARY",
                {"entrezGeneIds": [SMARCA2, SMARCA4], "sampleListId": f"{study}_all"})
    df = (pd.DataFrame([{"sample": d["sampleId"], "gene": d["entrezGeneId"], "v": d["value"]} for d in expr])
          .pivot(index="sample", columns="gene", values="v")
          .rename(columns={SMARCA2: "smarca2_protein", SMARCA4: "smarca4_protein"}).reset_index())
    df = df[df["sample"].isin(luad_lines & sequenced)].dropna(subset=["smarca2_protein"])
    m = pd.read_csv(f"{study}_smarca4_mutations.csv")  # written by fetch.py
    df["smarca4"] = [classify(m.loc[m["sample"] == s, "type"]) for s in df["sample"]]
    return df

if __name__ == "__main__":
    for name, d, out in [("CPTAC", fetch_cptac(), "cptac_luad_protein.csv"), ("CCLE", fetch_ccle(), "ccle_luad_protein.csv")]:
        d.to_csv(out, index=False)
        print(name, len(d), d["smarca4"].value_counts().to_dict())
