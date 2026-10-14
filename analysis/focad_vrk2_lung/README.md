# FOCAD deletion and VRK2 deficiency in lung cancer: DepMap → TCGA

**Question:** what do FOCAD-deleted and VRK2-deficient lung cancers depend on (DepMap), and how common are they in patient tumors (TCGA)?

## Pipeline
```
pip install pandas scipy matplotlib statsmodels
# DepMap 24Q4 from Figshare (article 27993248): Model, OmicsCNGene, OmicsAbsoluteCNGene,
# OmicsExpressionProteinCodingGenesTPMLogp1, CRISPRGeneEffect, OmicsSomaticMutations, OmicsSignatures
python3 -P depmap_build.py <DEPMAP_DIR>      # -> depmap_models.csv
python3 -P depmap_screen.py <DEPMAP_DIR>     # -> depmap_dependency_screen.csv, depmap_expression_correlations.csv, depmap_crispr_models.csv
python3 -P depmap_confounders.py             # -> depmap_confounder_checks.csv
python3 tcga_fetch.py                        # TCGA LUAD+LUSC via cBioPortal -> tcga_lung.csv, VRK2 methylation probes
python3 sclc_fetch.py                        # U Cologne SCLC via cBioPortal -> sclc_ucologne_expression.csv
python3 -P figures.py                        # -> fig1_depmap.png, fig2_tumors.png, tumor_frequencies.csv, depmap_lung_lines_summary.csv
```

## Definitions
- **FOCAD-deleted (cell lines):** FOCAD relative CN < 0.25 **and** FOCAD log2(TPM+1) < 1. Intact: relative CN ≥ 0.5.
- **9p21-matched control:** FOCAD-intact lines with MTAP homozygously deleted (relative CN < 0.25). FOCAD sits next to MTAP/CDKN2A, so this separates FOCAD effects from MTAP-loss effects.
- **VRK2-low (cell lines):** VRK2 log2(TPM+1) < 2; normal ≥ 3.
- **Tumors:** FOCAD deletion = GISTIC −2. VRK2-low = ≥ 8-fold below the cohort median.
- **Tests:** genome-wide Welch t with Benjamini–Hochberg FDR. Confounder checks use OLS with lineage fixed effects, MTAP deletion and MSI-high (MSIsensor2 ≥ 20) as covariates.

## SWI/SNF follow-up (`swisnf_angle.py`, `swisnf_tcga.py`)
- SWI/SNF loss = LikelyLoF mutation or homozygous deletion (DepMap); truncating mutation or GISTIC −2 (TCGA).
- `swisnf_depmap_checks.csv`: SWI/SNF loss → PELO/HBS1L dependency; SWI/SNF loss → SKI-complex expression; FOCAD-del × SWI/SNF interaction; FOCAD-del → SWI/SNF subunit dependency.
- `swisnf_focad_deleted_lines.csv`: the 39 FOCAD-deleted lines with their SWI/SNF status.
- `swisnf_tcga_overlap.csv`: co-occurrence of FOCAD deletion with SWI/SNF loss in TCGA LUAD/LUSC (Fisher's exact test).
