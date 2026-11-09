"""
03_seed_sensitivity.py — Block 1 (E.1)
Seed sensitivity analysis: 100 random states, n_init=1 vs n_init=50.
Manuscript: PONE-D-26-06286, Section: Methods - Reproducibility
Outputs: S1 Table, S1 Figure
"""
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import silhouette_score, adjusted_rand_score
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# Load and filter
data = pd.read_excel('../data/Dataset_final_revisado.xlsx')
data = data[data['resistencia promedio (mΩ)'] <= 400].copy().reset_index(drop=True)
cap = data['Capacidad descargada (Ah)'].values
res = data['resistencia promedio (mΩ)'].values
scaler = MinMaxScaler()
X = scaler.fit_transform(np.column_stack([cap, res]))
print(f"Cells: {len(X)}")

N_SEEDS = 100
results = {'seed': [], 'sil_ninit1': [], 'sil_ninit50': []}

for s in range(N_SEEDS):
    km1 = KMeans(n_clusters=6, random_state=s, n_init=1, max_iter=300, tol=1e-4)
    km50 = KMeans(n_clusters=6, random_state=s, n_init=50, max_iter=300, tol=1e-4)
    results['seed'].append(s)
    results['sil_ninit1'].append(silhouette_score(X, km1.fit_predict(X)))
    results['sil_ninit50'].append(silhouette_score(X, km50.fit_predict(X)))

df = pd.DataFrame(results)
s1, s50 = df['sil_ninit1'], df['sil_ninit50']

print(f"\nn_init=1:  {s1.mean():.4f} ± {s1.std():.4f} [{s1.min():.4f}, {s1.max():.4f}]")
print(f"n_init=50: {s50.mean():.4f} ± {s50.std():.4f} [{s50.min():.4f}, {s50.max():.4f}]")

# Pairwise ARI for n_init=50
all_labels = []
for s in range(N_SEEDS):
    km = KMeans(n_clusters=6, random_state=s, n_init=50, max_iter=300)
    all_labels.append(km.fit_predict(X))

aris = []
rng = np.random.RandomState(0)
idx = rng.choice(N_SEEDS, size=30, replace=False)
for i in range(len(idx)):
    for j in range(i+1, len(idx)):
        aris.append(adjusted_rand_score(all_labels[idx[i]], all_labels[idx[j]]))
aris = np.array(aris)
print(f"ARI (n_init=50): {aris.mean():.4f} ± {aris.std():.4f} [min={aris.min():.4f}]")

# Paper value reproduction
km_paper = KMeans(n_clusters=6, random_state=42, n_init=1, max_iter=300)
sil_paper = silhouette_score(X, km_paper.fit_predict(X))
print(f"\nPaper reproduction (rs=42, n_init=1): {sil_paper:.4f} (paper reports 0.460)")

# Save table
df.to_excel('../supplementary_tables/S1_Table_seed_sensitivity.xlsx', index=False)
print("\n✓ S1 Table saved")
