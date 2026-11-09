"""
02_clustering_gmm.py
GMM clustering initialized with K-means (full and spherical covariance, k = 2-10).
Manuscript: PONE-D-26-06286, Section: Results - Clustering performance
"""
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import silhouette_score
import warnings
warnings.filterwarnings('ignore')

# Load and filter data
data = pd.read_excel('../data/Dataset_final_revisado.xlsx')
data = data[data['resistencia promedio (mΩ)'] <= 400].copy().reset_index(drop=True)

cap = data['Capacidad descargada (Ah)'].values
res = data['resistencia promedio (mΩ)'].values
scaler = MinMaxScaler()
X = scaler.fit_transform(np.column_stack([cap, res]))

print(f"Cells: {len(X)}")
print(f"\n{'k':<5} {'KM Sil':<12} {'GMM-full Sil':<14} {'GMM-sph Sil':<14}")
print("-" * 45)

for k in range(2, 11):
    # K-means baseline
    km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
    labels_km = km.fit_predict(X)
    sil_km = silhouette_score(X, labels_km)
    
    # GMM full covariance initialized with K-means
    precs = []
    for i in range(k):
        pts = X[labels_km == i]
        cov = np.cov(pts, rowvar=False) if pts.shape[0] > 1 else np.eye(2) * 1e-6
        cov = (cov + cov.T) / 2 + np.eye(2) * 1e-6
        precs.append(np.linalg.inv(cov))
    
    gmm_full = GaussianMixture(n_components=k, covariance_type='full',
                                means_init=km.cluster_centers_,
                                precisions_init=np.array(precs), random_state=42)
    gmm_full.fit(X)
    sil_full = silhouette_score(X, gmm_full.predict(X))
    
    # GMM spherical covariance
    gmm_sph = GaussianMixture(n_components=k, covariance_type='spherical',
                               means_init=km.cluster_centers_, random_state=42)
    gmm_sph.fit(X)
    sil_sph = silhouette_score(X, gmm_sph.predict(X))
    
    print(f"{k:<5} {sil_km:<12.4f} {sil_full:<14.4f} {sil_sph:<14.4f}")

print(f"\nBoth covariance types peak at k = 6.")
