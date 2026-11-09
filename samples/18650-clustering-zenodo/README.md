# Dataset and Code — PONE-D-26-06286

## Citation
Olivero-Ortiz V, Oliveros Pantoja I, Mendoza Polo J, Robles-Algarín C, Ripoll Solano L. Clustering recovered 18650 lithium-ion cells to improve homogeneity in second-life battery pack construction. PLOS ONE. 2026.

## Description
This repository contains the experimental dataset and source code to reproduce all analyses reported in the manuscript.

## Dataset
- **Dataset_final_revisado.xlsx**: Electrical characterization of 92 recovered 18650 cells (3 resistance replicates per cell, discharged capacity, voltage measurements, discharge time, manufacturer, and chemistry labels).

## Software requirements
- Python 3.11+
- scikit-learn 1.4+
- NumPy 1.26+
- pandas 2.2+
- matplotlib 3.8+
- openpyxl 3.1+

Install dependencies: `pip install -r code/requirements.txt`

## Code description
| Script | Analysis | Manuscript section |
|--------|----------|--------------------|
| 01_clustering_kmeans.py | K-means clustering (k=2–10) | Results: Clustering performance |
| 02_clustering_gmm.py | GMM clustering (full + spherical, k=2–10) | Results: Clustering performance |
| 03_seed_sensitivity.py | 100-seed reproducibility analysis | Methods: Reproducibility protocol |
| 04_w_sensitivity.py | Weight coefficient sensitivity (w=0–1) | Methods: Adjusted SoH |
| 05_opus_repeatability.py | Measurement repeatability + Monte Carlo | Methods: Quick Test |
| 06_random_baseline.py | Random baseline (N=10,000) + significance | Results: Statistical comparison |
| 07_chemistry_analysis.py | Cluster × chemistry cross-tabulation | Results: Chemistry analysis |

## Usage
```bash
cd code
python 01_clustering_kmeans.py
python 02_clustering_gmm.py
python 03_seed_sensitivity.py
python 04_w_sensitivity.py
python 05_opus_repeatability.py
python 06_random_baseline.py
python 07_chemistry_analysis.py
```

## Supplementary tables
Pre-computed supplementary tables (S1–S6) are provided in the `supplementary_tables/` folder.

## License
CC-BY 4.0 (consistent with PLOS ONE publication license)
