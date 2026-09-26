# SMARCA2 expression by SMARCA4 mutation status — LUAD

- `fetch.py` pulls data from the cBioPortal API (TCGA PanCancer Atlas LUAD; CCLE Broad 2019, OncoTree `LUAD` lines only).
- `analyze.py` makes `smarca2_by_smarca4_luad.png` and writes `stats.csv`.

SMARCA4 status: WT = no SMARCA4 mutation in a sequenced sample; Truncating = nonsense, frameshift, splice or start/stop loss; Missense/other = any other mutation.
Expression is log2(RSEM+1) for TCGA and log2(RPKM+1) for CCLE. Tests are two-sided Mann–Whitney U (Welch t in the CSV too), plus Kruskal–Wallis across the three groups.
