# SMARCA2 expression by SMARCA4 mutation status — LUAD

| Level | Tumors | Cell lines | Figure / stats |
|---|---|---|---|
| mRNA | TCGA PanCancer Atlas LUAD (cBioPortal) | CCLE Broad 2019 (cBioPortal) | `smarca2_by_smarca4_luad.png`, `stats.csv` |
| Protein | CPTAC LUAD, Gillette 2020, UMich TMT (`cptac` package) | CCLE proteomics, Nusinow 2020 (cBioPortal) | `smarca2_protein_by_smarca4_luad.png`, `stats_protein.csv` |

Cell lines are restricted to OncoTree `LUAD`. TCGA RPPA has no SMARCA2 antibody, and cBioPortal's copy of CPTAC LUAD
drops SMARCA2/SMARCA4 from its protein matrix, which is why the CPTAC data come from the `cptac` package.

SMARCA4 status: WT = sequenced, no coding SMARCA4 mutation; Truncating = nonsense, frameshift, splice or start/stop loss;
Missense/other = any other coding mutation. Tests: two-sided Mann–Whitney U (Welch t in the CSVs), Kruskal–Wallis across
the three groups, Cliff's delta (negative = lower in the second group).

```
pip install pandas scipy matplotlib cptac
python3 fetch.py && python3 fetch_protein.py && python3 analyze.py   # or: analyze.py mrna | protein
```
