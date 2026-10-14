"""Copy number of genes around SMARCA4 (chr19:4-18 Mb, hg38) in TCGA PanCancer Atlas tumors (cBioPortal).

Outputs:
  genes_chr19.csv            gene, entrez, start/end (hg38, RefSeq Select from UCSC; chr19_refseq.json)
  pancan_smarca4_status.csv  SMARCA4 GISTIC + log2CN + truncating mutation for every PanCancer Atlas tumor
  pancan_homdel_region.csv   GISTIC (and log2CN) for every region gene in SMARCA4-homdel tumors
  lung_region_gistic.csv     GISTIC for every region gene in all TCGA LUAD/LUSC tumors
"""
import json, urllib.request
import pandas as pd

API = "https://www.cbioportal.org/api"
SMARCA4 = 6597
TRUNC = {"Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins", "Splice_Site", "Nonstop_Mutation", "Translation_Start_Site"}

def get(path):
    return json.load(urllib.request.urlopen(f"{API}/{path}"))

def post(path, body):
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))

def region_genes():
    rs = json.load(open("chr19_refseq.json"))["ncbiRefSeqSelect"]
    g = (pd.DataFrame([{"gene": r["name2"], "start": r["txStart"], "end": r["txEnd"]} for r in rs if r["name"].startswith("NM_")])
         .groupby("gene").agg(start=("start", "min"), end=("end", "max")).reset_index())
    ent = post("genes/fetch?geneIdType=HUGO_GENE_SYMBOL&projection=SUMMARY", g["gene"].tolist())
    g["entrez"] = g["gene"].map({e["hugoGeneSymbol"]: e["entrezGeneId"] for e in ent})
    return g.dropna(subset=["entrez"]).astype({"entrez": int}).sort_values("start")

def matrix(profile, entrez, sample_list=None, samples=None):
    body = {"entrezGeneIds": entrez}
    if sample_list: body["sampleListId"] = sample_list
    else: body["sampleIds"] = samples
    d = post(f"molecular-profiles/{profile}/molecular-data/fetch?projection=SUMMARY", body)
    return pd.DataFrame([{"sample": x["sampleId"], "entrez": x["entrezGeneId"], "v": x["value"]} for x in d])

if __name__ == "__main__":
    genes = region_genes(); genes.to_csv("genes_chr19.csv", index=False)
    studies = [s["studyId"] for s in get("studies?projection=SUMMARY") if s["studyId"].endswith("_tcga_pan_can_atlas_2018")]
    status, homdel_region, lung = [], [], []
    for st in studies:
        g = matrix(f"{st}_gistic", [SMARCA4], f"{st}_cna").rename(columns={"v": "SMARCA4_gistic"}).drop(columns="entrez")
        l2 = matrix(f"{st}_log2CNA", [SMARCA4], f"{st}_cna").rename(columns={"v": "SMARCA4_log2cn"}).drop(columns="entrez")
        mu = post(f"molecular-profiles/{st}_mutations/mutations/fetch?projection=SUMMARY",
                  {"entrezGeneIds": [SMARCA4], "sampleListId": f"{st}_all"})
        tr = {x["sampleId"] for x in mu if x["mutationType"] in TRUNC}
        s = g.merge(l2, on="sample", how="left"); s["SMARCA4_truncating"] = s["sample"].isin(tr); s["study"] = st
        status.append(s)
        hd = s.loc[s.SMARCA4_gistic == -2, "sample"].tolist()
        if hd:
            r = matrix(f"{st}_gistic", genes.entrez.tolist(), samples=hd).rename(columns={"v": "gistic"})
            r2 = matrix(f"{st}_log2CNA", genes.entrez.tolist(), samples=hd).rename(columns={"v": "log2cn"})
            homdel_region.append(r.merge(r2, on=["sample", "entrez"], how="left").assign(study=st))
        if st.startswith(("luad", "lusc")):
            lung.append(matrix(f"{st}_gistic", genes.entrez.tolist(), f"{st}_cna").assign(study=st))
        print(st, len(s), "SMARCA4 homdel:", len(hd), flush=True)
    pd.concat(status).to_csv("pancan_smarca4_status.csv", index=False)
    pd.concat(homdel_region).to_csv("pancan_homdel_region.csv", index=False)
    pd.concat(lung).rename(columns={"v": "gistic"}).to_csv("lung_region_gistic.csv", index=False)
