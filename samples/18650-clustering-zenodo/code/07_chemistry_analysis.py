"""
07_chemistry_analysis.py — A-08
Post-hoc analysis of cluster membership vs cell chemistry.
Manuscript: PONE-D-26-06286, Section: Results - Chemistry analysis
Outputs: S5 Table
"""
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler, LabelEncoder
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
import warnings
warnings.filterwarnings('ignore')

# Load and filter
data = pd.read_excel('../data/Dataset_final_revisado.xlsx')
data = data[data['resistencia promedio (mΩ)'] <= 400].copy().reset_index(drop=True)

cap = data['Capacidad descargada (Ah)'].values
res = data['resistencia promedio (mΩ)'].values
scaler = MinMaxScaler()
X = scaler.fit_transform(np.column_stack([cap, res]))

# GMM clustering (k=6, initialized with K-means)
km = KMeans(n_clusters=6, random_state=42, n_init=10)
labels_km = km.fit_predict(X)
precs = []
for i in range(6):
    pts = X[labels_km == i]
    cov = np.cov(pts, rowvar=False) if pts.shape[0] > 1 else np.eye(2)*1e-6
    cov = (cov + cov.T)/2 + np.eye(2)*1e-6
    precs.append(np.linalg.inv(cov))
gmm = GaussianMixture(n_components=6, covariance_type='full',
                       means_init=km.cluster_centers_,
                       precisions_init=np.array(precs), random_state=42)
gmm.fit(X)
labels_gmm = gmm.predict(X)

# Chemistry analysis
chem = data['quimica'].values
le = LabelEncoder()
chem_enc = le.fit_transform(chem)

ari = adjusted_rand_score(chem_enc, labels_gmm)
nmi = normalized_mutual_info_score(chem_enc, labels_gmm)

print(f"Cells: {len(data)}")
print(f"\n=== Cross-tabulation ===")
ct = pd.crosstab(labels_gmm, chem, margins=True, margins_name='Total')
ct.index = [f'Cluster {i}' if i != 'Total' else 'Total' for i in ct.index]
print(ct.to_string())

print(f"\nARI: {ari:.4f}")
print(f"NMI: {nmi:.4f}")

# Purity
total_purity = 0
for c in range(6):
    mask = labels_gmm == c
    if mask.sum() == 0: continue
    dominant = pd.Series(chem[mask]).value_counts()
    purity = dominant.iloc[0] / mask.sum()
    total_purity += dominant.iloc[0]
    print(f"Cluster {c}: n={mask.sum()}, dominant={dominant.index[0]} ({purity*100:.0f}%)")

print(f"\nGlobal purity: {total_purity/len(data):.3f}")

# Save
with pd.ExcelWriter('../supplementary_tables/S5_Table_chemistry.xlsx') as w:
    ct.to_excel(w, sheet_name='Cluster x Chemistry')
    ct_mfr = pd.crosstab(labels_gmm, data['fabricante '], margins=True, margins_name='Total')
    ct_mfr.index = [f'Cluster {i}' if i != 'Total' else 'Total' for i in ct_mfr.index]
    ct_mfr.to_excel(w, sheet_name='Cluster x Manufacturer')

print("\n✓ S5 Table saved")
