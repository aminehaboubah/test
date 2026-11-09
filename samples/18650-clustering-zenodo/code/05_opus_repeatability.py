"""
05_opus_repeatability.py — Block 3 (R1.3 + E.2)
OPUS BT-C3400 repeatability analysis + Monte Carlo noise propagation.
Manuscript: PONE-D-26-06286, Section: Methods - Quick Test
Outputs: S3 Table, S3 Figure
"""
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import silhouette_samples
import warnings
warnings.filterwarnings('ignore')

# Load full data (92 cells for metrological analysis)
data = pd.read_excel('../data/Dataset_final_revisado.xlsx')

r1 = data['resistencia testeada1 (mΩ)'].values
r2 = data['resistencia testeada2 (mΩ)'].values
r3 = data['resistencia testiada3 (mΩ)'].values
R = np.column_stack([r1, r2, r3])

r_mean = R.mean(axis=1)
r_std = R.std(axis=1, ddof=1)
r_cv = (r_std / r_mean) * 100

print(f"=== Repeatability (92 cells) ===")
print(f"Median CV: {np.median(r_cv):.2f}%")
print(f"Mean CV:   {np.mean(r_cv):.2f}%")
print(f"P95 CV:    {np.percentile(r_cv, 95):.2f}%")
print(f"Cells CV < 5%:  {(r_cv < 5).sum()}/92 ({(r_cv < 5).sum()/92*100:.0f}%)")
print(f"Cells CV > 20%: {(r_cv > 20).sum()}/92")

# Save per-cell table
df_cv = pd.DataFrame({
    'COD': data['COD'], 'R1_mOhm': r1, 'R2_mOhm': r2, 'R3_mOhm': r3,
    'Mean_R': np.round(r_mean, 1), 'SD_R': np.round(r_std, 1), 'CV_pct': np.round(r_cv, 2)
})
df_cv.to_excel('../supplementary_tables/S3_Table_repeatability.xlsx', index=False)

# Monte Carlo propagation (91 cells for clustering)
data_filt = data[data['resistencia promedio (mΩ)'] <= 400].copy().reset_index(drop=True)
cap = data_filt['Capacidad descargada (Ah)'].values
res = data_filt['resistencia promedio (mΩ)'].values
R_f = np.column_stack([
    data_filt['resistencia testeada1 (mΩ)'].values,
    data_filt['resistencia testeada2 (mΩ)'].values,
    data_filt['resistencia testiada3 (mΩ)'].values
])

scaler = MinMaxScaler()
X = scaler.fit_transform(np.column_stack([cap, res]))
km = KMeans(n_clusters=6, random_state=42, n_init=50, max_iter=300)
labels = km.fit_predict(X)
sil_s = silhouette_samples(X, labels)

# Baseline selection (V1: top 4 cells per cluster by silhouette)
sel_base = []
for c in range(6):
    mask = labels == c
    cidx = np.where(mask)[0]
    if len(cidx) >= 4:
        sel_base.extend(cidx[np.argsort(sil_s[mask])[-4:]].tolist())
sel_base = sorted(sel_base[:24])

B = 500
caps_mc, rs_mc = [], []
for b in range(B):
    rng = np.random.RandomState(b)
    r_boot = np.array([R_f[i, rng.randint(0, 3, size=3)].mean() for i in range(len(R_f))])
    X_n = scaler.fit_transform(np.column_stack([cap, r_boot]))
    km_b = KMeans(n_clusters=6, random_state=42, n_init=50, max_iter=300)
    lb = km_b.fit_predict(X_n)
    ss = silhouette_samples(X_n, lb)
    sel = []
    for c in range(6):
        m = lb == c; ci = np.where(m)[0]
        if len(ci) >= 4: sel.extend(ci[np.argsort(ss[m])[-4:]].tolist())
    sel = sorted(sel[:24])
    caps_mc.append(cap[sel].sum())
    rs_mc.append(r_boot[sel].mean())

caps_mc, rs_mc = np.array(caps_mc), np.array(rs_mc)
print(f"\n=== Monte Carlo (B={B}, 91 cells) ===")
print(f"Capacity CV: {caps_mc.std()/caps_mc.mean()*100:.2f}%")
print(f"Resistance CV: {rs_mc.std()/rs_mc.mean()*100:.2f}%")
print("\n✓ S3 Table saved")
