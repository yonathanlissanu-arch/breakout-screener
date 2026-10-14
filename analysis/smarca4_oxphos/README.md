# Why are SMARCA4-deficient NSCLC sensitive to OXPHOS inhibition? Genetics + metabolic expression

```
pip install pandas scipy statsmodels matplotlib
python3 -P depmap_analysis.py <DEPMAP_24Q4_DIR>   # cell-line expression DE + gene-set tests + CRISPR dependency
python3 -P depmap_adjusted.py <DEPMAP_24Q4_DIR>   # metabolic scores/genes adjusted for STK11/KEAP1/subtype
python3 tcga_validate.py                          # TCGA LUAD validation of the metabolic signature (cBioPortal)
python3 -P figure.py                              # -> fig_smarca4_oxphos.png
```

## Group definitions
- **Cell lines (DepMap 24Q4 NSCLC, n=137):** deficient = SMARCA4 LikelyLoF mutation OR SMARCA4 log2(TPM+1) < 3 (35); WT = no SMARCA4 mutation AND log2(TPM+1) ≥ 5 (102). Robust to using LoF-only (n=30) or expr-low-only (n=7).
- **Tumors (TCGA LUAD, n=422 analyzed):** deficient = truncating SMARCA4 mutation OR SMARCA4 mRNA z ≤ −2 (38); WT = no mutation AND z ≥ −0.5 (384).
- Tests: Welch t with BH-FDR (genome-wide); gene-set shift = Mann–Whitney of member t-stats vs all genes; OLS adjustment for STK11 / KEAP1 / subtype.

## Files
| File | Contents |
|---|---|
| `depmap_nsclc_lines.csv`, `depmap_nsclc_lines_scored.csv` | the cell lines, SMARCA4 status, STK11/KEAP1, metabolic scores |
| `depmap_expression_de.csv`, `depmap_expression_gene_sets.csv` | genome-wide expression DE and metabolic gene-set shifts |
| `depmap_crispr_de.csv`, `depmap_crispr_gene_sets.csv` | CRISPR dependency DE and gene-set shifts |
| `depmap_adjusted_models.csv` | metabolic genes/scores adjusted for STK11/KEAP1/subtype |
| `tcga_luad_gene_stats.csv`, `tcga_luad_signature.csv` | TCGA validation per gene and per tumor |
| `gene_sets.py` | curated metabolic gene sets |
