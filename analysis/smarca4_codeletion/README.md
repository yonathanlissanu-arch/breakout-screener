# Genes co-deleted with SMARCA4 (19p13.2)

```
pip install pandas scipy matplotlib
python3 tcga_fetch.py                 # TCGA PanCancer Atlas copy number, chr19:4-18 Mb (cBioPortal); gene coordinates from UCSC (chr19_refseq.json)
python3 -P extents.py                 # -> homdel_extents.csv (contiguous GISTIC -2 run containing SMARCA4, per tumor)
python3 tcga_expression_check.py      # mRNA z-scores for SMARCA4, neighbours and essential genes in each homdel tumor
python3 -P summarize.py               # -> codeletion_frequency_focal.csv
python3 lung_het_loss.py              # lung one-copy loss profile + SMARCA4/KEAP1
python3 -P depmap_check.py <DEPMAP_24Q4_DIR>
python3 -P figure.py                  # -> fig_smarca4_codeletion.png
```

## Files
| File | Contents |
|---|---|
| `homdel_extents.csv` | each TCGA tumor with SMARCA4 GISTIC −2: study, contiguous co-deleted genes, size, SMARCA4 mRNA z |
| `homdel_expression_check.csv` | mRNA z-scores for SMARCA4, neighbours and essential genes in those tumors |
| `codeletion_frequency_focal.csv` | per-gene co-deletion among focal (≤ 2 Mb) and mRNA-confirmed events |
| `lung_single_copy_loss_profile.csv` | % one-copy loss of each neighbour in TCGA LUAD/LUSC, overall and given SMARCA4 loss |
| `lung_smarca4_keap1_summary.csv` | SMARCA4-truncated lung tumors: SMARCA4 LOH, KEAP1 one-copy loss and KEAP1 mutation |
| `depmap_smarca4_homdel_lines.csv`, `depmap_codeletion_frequency.csv` | DepMap 24Q4 cell lines with SMARCA4 relative CN < 0.25 |

## Definitions
- Homozygous deletion = GISTIC −2. A call is mRNA-confirmed when SMARCA4 z ≤ −2 against all tumors of the same study.
- Calls larger than 2 Mb are treated as not credible 0-copy losses: SMARCA4 and common-essential genes inside them (EIF3G, CDC37, DNMT1) are still expressed.
- One-copy loss = GISTIC ≤ −1. Truncating = nonsense, frameshift, splice site.
