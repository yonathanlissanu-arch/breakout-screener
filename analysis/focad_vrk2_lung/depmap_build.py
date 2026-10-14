"""Build a per-cell-line table for all DepMap 24Q4 models: FOCAD/VRK2 (and 9p21 neighbours) CN, expression, mutations.

Usage: python3 -P depmap_build.py <DEPMAP_DIR>
"""
import sys
import pandas as pd

D = sys.argv[1]
GENES = ["FOCAD", "MTAP", "CDKN2A", "CDKN2B", "VRK2", "VRK1"]

def cols_for(path, genes):
    header = pd.read_csv(path, nrows=0).columns
    pick = {c: c.split(" (")[0] for c in header[1:] if c.split(" (")[0] in genes}
    return header[0], pick

def gene_table(fname, suffix):
    path = f"{D}/{fname}"
    index_col, pick = cols_for(path, GENES)
    df = pd.read_csv(path, usecols=[index_col] + list(pick), index_col=index_col).rename(columns=pick)
    return df.add_suffix(suffix)

if __name__ == "__main__":
    model = pd.read_csv(f"{D}/Model.csv", index_col="ModelID")
    models = model[["CellLineName", "OncotreeLineage", "OncotreePrimaryDisease", "OncotreeSubtype", "OncotreeCode"]]
    rel = gene_table("OmicsCNGene.csv", "_relcn")
    absn = gene_table("OmicsAbsoluteCNGene.csv", "_abscn")
    expr = gene_table("OmicsExpressionProteinCodingGenesTPMLogp1.csv", "_expr")
    crispr = gene_table("CRISPRGeneEffect.csv", "_gene_effect")
    df = models.join([rel, absn, expr, crispr])
    muts = pd.read_csv(f"{D}/OmicsSomaticMutations.csv",
                       usecols=["ModelID", "HugoSymbol", "ProteinChange", "VariantInfo", "LikelyLoF"])
    for g in ["FOCAD", "VRK2"]:
        m = muts[muts["HugoSymbol"] == g]
        df[f"{g}_mutation"] = df.index.map(m.groupby("ModelID")["ProteinChange"].agg(lambda x: "; ".join(f"{v}" for v in x))).fillna("")
        df[f"{g}_lof_mutation"] = df.index.isin(m.loc[m["LikelyLoF"] == True, "ModelID"])
    df["has_crispr"] = df.index.isin(crispr.index)
    df.rename_axis("ModelID").to_csv("depmap_models.csv")
    print(df.shape, "with CRISPR:", df["has_crispr"].sum())
