"""
01_clustering_kmeans.py
K-means clustering of recovered 18650 cells (k = 2-10).
Manuscript: PONE-D-26-06286, Section: Results - Clustering performance
"""
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import silhouette_score
import warnings
warnings.filterwarnings('ignore')

# Load and filter data
data = pd.read_excel('../data/Dataset_final_revisado.xlsx')
data = data[data['resistencia promedio (mΩ)'] <= 400].copy().reset_index(drop=True)
print(f"Cells after filtering (R <= 400 mΩ): {len(data)}")

# Features for clustering
cap = data['Capacidad descargada (Ah)'].values
res = data['resistencia promedio (mΩ)'].values
scaler = MinMaxScaler()
X = scaler.fit_transform(np.column_stack([cap, res]))

# K-means clustering for k = 2 to 10
print(f"\n{'k':<5} {'Silhouette':<12} {'Inertia':<12}")
print("-" * 30)

results = []
for k in range(2, 11):
    km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300, tol=1e-4)
    labels = km.fit_predict(X)
    sil = silhouette_score(X, labels)
    results.append({'k': k, 'silhouette': sil, 'inertia': km.inertia_})
    print(f"{k:<5} {sil:<12.4f} {km.inertia_:<12.4f}")

# Best k
best = max(results, key=lambda x: x['silhouette'])
print(f"\nBest k = {best['k']} (Silhouette = {best['silhouette']:.4f})")

# Export cluster assignments at k = 6
km_best = KMeans(n_clusters=6, random_state=42, n_init=10, max_iter=300)
labels_best = km_best.fit_predict(X)
data['cluster_kmeans'] = labels_best
print(f"\nCluster sizes at k = 6: {np.bincount(labels_best)}")
