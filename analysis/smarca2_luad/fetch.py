"""Fetch SMARCA2 expression + SMARCA4 mutations for LUAD tumors (TCGA) and LUAD cell lines (CCLE) from cBioPortal."""
import json, urllib.request
import pandas as pd

API = "https://www.cbioportal.org/api"
SMARCA2, SMARCA4 = 6595, 6597  # Entrez IDs

def post(path, body):
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req))

def get(path):
    return json.load(urllib.request.urlopen(f"{API}/{path}"))

def fetch(study, expr_profile, extra_filter=None):
    sequenced = {s for s in get(f"sample-lists/{study}_sequenced")["sampleIds"]}
    expr = post(f"molecular-profiles/{expr_profile}/molecular-data/fetch?projection=SUMMARY",
                {"entrezGeneIds": [SMARCA2], "sampleListId": f"{study}_all"})
    df = pd.DataFrame([{"sample": d["sampleId"], "smarca2": d["value"]} for d in expr])
    muts = post(f"molecular-profiles/{study}_mutations/mutations/fetch?projection=DETAILED",
                {"entrezGeneIds": [SMARCA4], "sampleListId": f"{study}_all"})
    m = pd.DataFrame([{"sample": d["sampleId"], "type": d["mutationType"], "aa": d["proteinChange"]} for d in muts])
    m.to_csv(f"{study}_smarca4_mutations.csv", index=False)
    trunc = {"Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins", "Splice_Site", "Nonstop_Mutation",
             "Translation_Start_Site", "Splice_Region"}
    def status(s):
        mm = m[m["sample"] == s]
        if mm.empty: return "WT"
        return "Truncating" if mm["type"].isin(trunc).any() else "Missense/other"
    df = df[df["sample"].isin(sequenced)].copy()
    df["smarca4"] = df["sample"].map(status)
    return df

tcga = fetch("luad_tcga_pan_can_atlas_2018", "luad_tcga_pan_can_atlas_2018_rna_seq_v2_mrna")
tcga.to_csv("tcga_luad.csv", index=False)

# CCLE: keep lung adenocarcinoma lines
samples = get("studies/ccle_broad_2019/samples?projection=SUMMARY&pageSize=10000")
cd = post("studies/ccle_broad_2019/clinical-data/fetch?clinicalDataType=SAMPLE",
          {"attributeIds": ["ONCOTREE_CODE", "CANCER_TYPE_DETAILED"], "ids": [s["sampleId"] for s in samples]})
clin = pd.DataFrame(cd).pivot_table(index="sampleId", columns="clinicalAttributeId", values="value", aggfunc="first")
luad_lines = set(clin.index[clin["ONCOTREE_CODE"] == "LUAD"])
ccle = fetch("ccle_broad_2019", "ccle_broad_2019_rna_seq_mrna")
ccle = ccle[ccle["sample"].isin(luad_lines)]
ccle.to_csv("ccle_luad.csv", index=False)
for n, d in [("TCGA", tcga), ("CCLE", ccle)]:
    print(n, len(d)); print(d["smarca4"].value_counts()); print(d["smarca2"].describe())
