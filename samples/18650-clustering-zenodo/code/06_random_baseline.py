"""
06_random_baseline.py — Block 4 (R1.5 + Add.4)
Random-selection baseline (N=10,000) and statistical significance analysis.
Manuscript: PONE-D-26-06286, Section: Results - Statistical comparison
Outputs: S4 Table
"""
import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

# Load cluster 2 data (working cluster for V1/V2 selection)
# Note: cluster 2 is exported from the GMM partition at k=6
data = pd.read_excel('../data/Dataset_final_revisado.xlsx')
data = data[data['resistencia promedio (mΩ)'] <= 400].copy().reset_index(drop=True)

from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler

cap_all = data['Capacidad descargada (Ah)'].values
res_all = data['resistencia promedio (mΩ)'].values
scaler = MinMaxScaler()
X = scaler.fit_transform(np.column_stack([cap_all, res_all]))

# Reproduce GMM partition to identify cluster 2
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

# Working cluster = largest cluster
c2_label = np.argmax([(labels_gmm == c).sum() for c in range(6)])
c2_mask = labels_gmm == c2_label
cap_c2 = cap_all[c2_mask]
res_c2 = res_all[c2_mask]
n_c2 = len(cap_c2)

# Pack topology
s, p = 4, 6
n_pack = s * p
V_nom = 3.7

def pack_metrics(c_sel, r_sel):
    cs = c_sel.reshape(p, s)
    rs = r_sel.reshape(p, s)
    pack_cap = cs.min(axis=1).sum()
    str_res = rs.sum(axis=1)
    pack_res = 1.0 / np.sum(1.0 / str_res)
    p_max = (s * V_nom)**2 / (4 * pack_res / 1000)
    return pack_cap, pack_res, p_max

# Table 2 reference values
T2_V1 = {'cap': 8.72, 'res': 78.90, 'pmax': 694.08}
T2_V2 = {'cap': 8.98, 'res': 76.38, 'pmax': 716.97}

# Random baseline
N = 10000
rng = np.random.RandomState(42)
rand_caps, rand_res, rand_pmax = [], [], []

for i in range(N):
    idx = rng.choice(n_c2, size=n_pack, replace=False)
    rng.shuffle(idx)
    c, r, pm = pack_metrics(cap_c2[idx], res_c2[idx])
    rand_caps.append(c); rand_res.append(r); rand_pmax.append(pm)

rc, rr, rp = np.array(rand_caps), np.array(rand_res), np.array(rand_pmax)

print(f"Working cluster: {n_c2} cells")
print(f"\n=== Random baseline (N={N}) ===")
print(f"Capacity:   {rc.mean():.2f} ± {rc.std():.2f} Ah, 95%CI [{np.percentile(rc,2.5):.2f}, {np.percentile(rc,97.5):.2f}]")
print(f"Resistance: {rr.mean():.2f} ± {rr.std():.2f} mΩ")
print(f"P_max:      {rp.mean():.1f} ± {rp.std():.1f} W")

print(f"\n=== Percentiles ===")
print(f"V1 Cap {T2_V1['cap']}: {(rc<=T2_V1['cap']).mean()*100:.1f}th")
print(f"V2 Cap {T2_V2['cap']}: {(rc<=T2_V2['cap']).mean()*100:.1f}th")
print(f"V2 Res {T2_V2['res']}: {(rr>=T2_V2['res']).mean()*100:.1f}th (lower=better)")

print(f"\n=== Cohen's d ===")
print(f"V1 cap: {(T2_V1['cap']-rc.mean())/rc.std():.2f}")
print(f"V2 cap: {(T2_V2['cap']-rc.mean())/rc.std():.2f}")
print(f"V2 res: {(rr.mean()-T2_V2['res'])/rr.std():.2f}")

print(f"\n=== p-values (permutation, N={N}) ===")
delta_cap = T2_V2['cap'] - T2_V1['cap']
delta_res = T2_V1['res'] - T2_V2['res']
pair_dc, pair_dr = [], []
for i in range(N):
    i1 = rng.choice(n_c2, size=n_pack, replace=False); rng.shuffle(i1)
    i2 = rng.choice(n_c2, size=n_pack, replace=False); rng.shuffle(i2)
    c1,_,_ = pack_metrics(cap_c2[i1], res_c2[i1])
    c2r,r2,_ = pack_metrics(cap_c2[i2], res_c2[i2])
    pair_dc.append(abs(c2r-c1)); pair_dr.append(abs(rr.mean()-r2))
print(f"p(ΔCap≥{delta_cap:.2f}): {np.mean(np.array(pair_dc)>=delta_cap):.4f}")
print(f"p(ΔRes≥{delta_res:.2f}): {np.mean(np.array(pair_dr)>=delta_res):.4f}")

print("\n✓ Analysis complete")
