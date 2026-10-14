"""Curated metabolic gene sets (HGNC symbols)."""
GENE_SETS = {
    "Glucose uptake (GLUTs)": ["SLC2A1", "SLC2A3", "SLC2A4", "SLC2A2"],
    "Glycolysis (core enzymes)": ["HK1", "HK2", "HK3", "GPI", "PFKL", "PFKM", "PFKP", "ALDOA", "ALDOC", "TPI1",
                                  "GAPDH", "PGK1", "PGAM1", "ENO1", "ENO2", "PKM", "PKLR"],
    "Glycolysis regulators (PFKFB)": ["PFKFB1", "PFKFB2", "PFKFB3", "PFKFB4", "TIGAR"],
    "Lactate (LDH, MCT)": ["LDHA", "LDHB", "SLC16A1", "SLC16A3", "SLC16A7", "BSG"],
    "Pentose phosphate": ["G6PD", "PGLS", "PGD", "RPIA", "RPE", "TKT", "TALDO1"],
    "Glycogen": ["GYS1", "GBE1", "PYGB", "PYGL", "AGL", "UGP2", "PGM1"],
    "Gluconeogenesis (reverse)": ["PCK1", "PCK2", "FBP1", "FBP2", "G6PC1", "G6PC3"],
    "Pyruvate entry to TCA": ["MPC1", "MPC2", "PDHA1", "PDHB", "DLAT", "PDHX", "PDK1", "PDK2", "PDK3", "PDK4", "PDP1"],
    "TCA cycle": ["CS", "ACO2", "IDH2", "IDH3A", "IDH3B", "IDH3G", "OGDH", "DLST", "DLD", "SUCLA2", "SUCLG1",
                  "SUCLG2", "SDHA", "SDHB", "SDHC", "SDHD", "FH", "MDH2"],
    "Glutaminolysis": ["SLC1A5", "SLC38A2", "GLS", "GLS2", "GLUD1", "GOT1", "GOT2", "GPT2"],
    "Mito biogenesis / OXPHOS TFs": ["PPARGC1A", "PPARGC1B", "ESRRA", "NRF1", "TFAM", "TFB2M", "POLRMT"],
    "Hypoxia / HIF": ["HIF1A", "EPAS1", "ARNT", "VHL", "EGLN1", "EGLN3", "CA9", "VEGFA", "BNIP3", "NDRG1"],
}

def oxphos_genes(symbols):
    pre = ("NDUFA", "NDUFB", "NDUFC", "NDUFS", "NDUFV", "UQCR", "COX4", "COX5", "COX6", "COX7", "COX8", "ATP5")
    return [s for s in symbols if s.startswith(pre) or s in {"SDHA", "SDHB", "SDHC", "SDHD", "CYC1"}]
