"""SWI/SNF angle on the FOCAD -> PELO/HBS1L finding.

1. Do SWI/SNF-deficient lines (LoF mutation or homozygous deletion) share PELO/HBS1L dependency,
   independent of MSI, FOCAD/MTAP deletion and lineage?
2. Does SWI/SNF loss lower FOCAD / SKI-complex expression (a phenocopy route)?
3. Within FOCAD-deleted lines, does SWI/SNF status modify PELO/HBS1L dependency?
4. Is SMARCA2 (or other SWI/SNF) dependency altered in FOCAD-deleted lines?

Usage: python3 -P swisnf_angle.py <DEPMAP_DIR>   (needs depmap_crispr_models.csv)
"""
import sys
import numpy as np, pandas as pd
import statsmodels.formula.api as smf

D = sys.argv[1]
SWISNF = ["SMARCA4", "ARID1A", "ARID1B", "ARID2", "PBRM1", "SMARCB1", "SMARCA2"]
SKI = ["FOCAD", "SKIV2L", "TTC37", "WDR61", "PELO", "HBS1L"]

def matrix(fname, genes):
    header = pd.read_csv(f"{D}/{fname}", nrows=0).columns
    pick = {c: c.split(" (")[0] for c in header[1:] if c.split(" (")[0] in genes}
    return pd.read_csv(f"{D}/{fname}", usecols=[header[0]] + list(pick), index_col=header[0]).rename(columns=pick)

m = pd.read_csv("depmap_crispr_models.csv", index_col=0)
m["lineage"] = m["OncotreeLineage"].fillna("Other")
m["focad_del"] = (m.FOCAD_group == "FOCAD-deleted").astype(int)
m["mtap_del"] = (m.MTAP_relcn < 0.25).astype(int)
m["msi"] = m.MSI_high.astype(int)

muts = pd.read_csv(f"{D}/OmicsSomaticMutations.csv", usecols=["ModelID", "HugoSymbol", "LikelyLoF"])
lof = muts[(muts.LikelyLoF == True) & muts.HugoSymbol.isin(SWISNF)]
cn = matrix("OmicsCNGene.csv", SWISNF)
expr = matrix("OmicsExpressionProteinCodingGenesTPMLogp1.csv", SWISNF + SKI)
ge = matrix("CRISPRGeneEffect.csv", SWISNF)
for g in SWISNF:
    hit = set(lof.loc[lof.HugoSymbol == g, "ModelID"]) | set(cn.index[cn[g] < 0.25])
    m[f"{g}_loss"] = m.index.isin(hit).astype(int)
m = m.join(expr.add_suffix("_expr2"), how="left").join(ge.add_suffix("_ge"), how="left")
m["any_swisnf_loss"] = m[[f"{g}_loss" for g in SWISNF if g != "SMARCA2"]].max(axis=1)

rows = []
def fit(formula, data, term, outcome, label):
    f = smf.ols(formula, data=data.dropna(subset=[outcome])).fit()
    rows.append(dict(question=label, outcome=outcome, term=term, coef=f.params.get(term, np.nan),
                     p=f.pvalues.get(term, np.nan), n=int(f.nobs), n_altered=int(data.dropna(subset=[outcome])[term].sum()) if term in data.columns and set(data[term].dropna().unique()) <= {0, 1} else np.nan))

adj = "focad_del + mtap_del + msi + C(lineage)"
for g in SWISNF + ["any_swisnf"]:
    t = f"{g}_loss"
    for out in ["PELO_effect", "HBS1L_effect"]:
        fit(f"{out} ~ {t} + {adj}", m, t, out, "1. SWI/SNF loss -> PELO/HBS1L dependency (adj. FOCAD/MTAP/MSI/lineage)")
for g in ["SMARCA4", "ARID1A", "any_swisnf"]:
    t = f"{g}_loss"
    for out in ["FOCAD_expr2", "SKIV2L_expr2", "TTC37_expr2", "WDR61_expr2"]:
        fit(f"{out} ~ {t} + mtap_del + msi + C(lineage)", m[m.focad_del == 0], t, out,
            "2. SWI/SNF loss -> SKI-complex expression (FOCAD-intact lines, adj.)")
for out in ["PELO_effect", "HBS1L_effect"]:
    fit(f"{out} ~ focad_del * any_swisnf_loss + mtap_del + msi + C(lineage)", m, "focad_del:any_swisnf_loss", out,
        "3. Interaction FOCAD-del x SWI/SNF loss")
for g in SWISNF:
    fit(f"{g}_ge ~ focad_del + mtap_del + msi + C(lineage)", m, "focad_del", f"{g}_ge",
        "4. FOCAD-del -> SWI/SNF subunit dependency (adj.)")
# SKI complex expression as a continuous PELO biomarker (does low SKI expression phenocopy?)
for g in ["SKIV2L", "TTC37", "WDR61", "FOCAD"]:
    fit(f"PELO_effect ~ {g}_expr2 + msi + C(lineage)", m[m.focad_del == 0], f"{g}_expr2", "PELO_effect",
        "5. SKI-complex expression -> PELO dependency (FOCAD-intact lines)")

res = pd.DataFrame(rows)
res.to_csv("swisnf_depmap_checks.csv", index=False)
pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 80)
print(res.to_string(index=False, float_format=lambda x: f"{x:.3g}"))

# FOCAD-deleted lines: SWI/SNF status and PELO/HBS1L
fd = m[m.focad_del == 1]
cols = ["CellLineName", "lineage", "PELO_effect", "HBS1L_effect"] + [f"{g}_loss" for g in SWISNF if g != "SMARCA2"]
fd[cols].sort_values("PELO_effect").round(2).to_csv("swisnf_focad_deleted_lines.csv")
print("\nFOCAD-deleted lines with any SWI/SNF loss:", int(fd.any_swisnf_loss.sum()), "of", len(fd))
print(fd.groupby("any_swisnf_loss")[["PELO_effect", "HBS1L_effect"]].agg(["median", "count"]).round(2))
lung = m[m.lineage == "Lung"]
print("\nLung: PELO/HBS1L median by SMARCA4 loss (FOCAD-intact):")
print(lung[lung.focad_del == 0].groupby("SMARCA4_loss")[["PELO_effect", "HBS1L_effect"]].agg(["median", "count"]).round(2))
print(fd[fd.lineage == "Lung"][cols].round(2).to_string())

# ARID1A: how much of the PELO signal is MSI? (ARID1A frameshifts are enriched in MSI tumors)
print("\nARID1A loss vs MSI-high:", pd.crosstab(m.ARID1A_loss, m.msi).to_dict())
for label, formula, data in [
        ("unadjusted", "PELO_effect ~ ARID1A_loss", m),
        ("+ lineage", "PELO_effect ~ ARID1A_loss + C(lineage)", m),
        ("+ lineage + MSI + FOCAD/MTAP", f"PELO_effect ~ ARID1A_loss + {adj}", m),
        ("MSS lines only, + lineage + FOCAD/MTAP", "PELO_effect ~ ARID1A_loss + focad_del + mtap_del + C(lineage)", m[m.msi == 0])]:
    f = smf.ols(formula, data=data).fit()
    print(f"ARID1A -> PELO, {label}: coef={f.params['ARID1A_loss']:.3f} p={f.pvalues['ARID1A_loss']:.2g} n={int(f.nobs)}")
