"""Fetch FOCAD / VRK2 copy number, expression, mutations and VRK2 methylation for TCGA LUAD + LUSC (cBioPortal)."""
import json, urllib.request
import pandas as pd

API = "https://www.cbioportal.org/api"
GENES = {"FOCAD": 54914, "MTAP": 4507, "CDKN2A": 1029, "CDKN2B": 1030, "VRK2": 7444, "VRK1": 7443}
STUDIES = {"LUAD": "luad_tcga_pan_can_atlas_2018", "LUSC": "lusc_tcga_pan_can_atlas_2018"}

def get(path):
    return json.load(urllib.request.urlopen(f"{API}/{path}"))

def post(path, body):
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req))

def gene_matrix(profile, sample_list):
    d = post(f"molecular-profiles/{profile}/molecular-data/fetch?projection=SUMMARY",
             {"entrezGeneIds": list(GENES.values()), "sampleListId": sample_list})
    sym = {v: k for k, v in GENES.items()}
    return (pd.DataFrame([{"sample": x["sampleId"], "gene": sym[x["entrezGeneId"]], "v": x["value"]} for x in d])
            .pivot(index="sample", columns="gene", values="v"))

def fetch_study(tumor, study):
    gistic = gene_matrix(f"{study}_gistic", f"{study}_cna").add_suffix("_gistic")
    log2cn = gene_matrix(f"{study}_log2CNA", f"{study}_all").add_suffix("_log2cn")
    mrna = gene_matrix(f"{study}_rna_seq_v2_mrna", f"{study}_all").add_suffix("_rsem")
    df = gistic.join([log2cn, mrna], how="outer")
    muts = post(f"molecular-profiles/{study}_mutations/mutations/fetch?projection=DETAILED",
                {"entrezGeneIds": [GENES["FOCAD"], GENES["VRK2"]], "sampleListId": f"{study}_all"})
    m = pd.DataFrame([{"sample": x["sampleId"], "gene": x["gene"]["hugoGeneSymbol"],
                       "type": x["mutationType"], "aa": x["proteinChange"]} for x in muts])
    for g in ["FOCAD", "VRK2"]:
        mm = m[m["gene"] == g].groupby("sample").apply(lambda x: "; ".join(x["aa"] + " (" + x["type"] + ")"))
        df[f"{g}_mutation"] = df.index.map(mm).fillna("")
    sequenced = set(get(f"sample-lists/{study}_sequenced")["sampleIds"])
    df["sequenced"] = df.index.isin(sequenced)
    # VRK2 promoter methylation (HM450 beta values, VRK2 TSS200 / 5'UTR probes)
    meth_prof = f"{study}_methylation_hm450"
    meta = get(f"generic-assay-meta/{meth_prof}?projection=SUMMARY")
    probes = [e["stableId"] for e in meta
              if "VRK2" in e["genericEntityMetaProperties"].get("NAME", "").split(";")]
    samples = get(f"studies/{study}/samples?projection=ID&pageSize=10000")
    meth = post(f"generic_assay_data/{meth_prof}/fetch",
                {"genericAssayStableIds": probes, "sampleIds": [s["sampleId"] for s in samples]})
    meth = (pd.DataFrame([{"sample": x["sampleId"], "probe": x["stableId"], "beta": x["value"]} for x in meth])
            .assign(beta=lambda x: pd.to_numeric(x["beta"], errors="coerce"))
            .pivot(index="sample", columns="probe", values="beta"))
    meth.to_csv(f"tcga_{tumor.lower()}_vrk2_methylation_probes.csv")
    df.insert(0, "tumor_type", tumor)
    return df.rename_axis("sample").reset_index()

if __name__ == "__main__":
    out = pd.concat([fetch_study(t, s) for t, s in STUDIES.items()])
    out.to_csv("tcga_lung.csv", index=False)
    print(out.groupby("tumor_type").size())
    print(out.filter(like="_gistic").apply(pd.Series.value_counts).fillna(0))
