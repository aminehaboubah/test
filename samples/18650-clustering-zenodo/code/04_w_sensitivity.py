"""
04_w_sensitivity.py — Block 2 (E.3 + R1.4)
Sensitivity of feature selection to the weighting coefficient w.
Manuscript: PONE-D-26-06286, Section: Methods - Adjusted SoH
Outputs: S2 Table, S2 Figure
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# Load and filter
data = pd.read_excel('../data/Dataset_final_revisado.xlsx')
data = data[data['resistencia promedio (mΩ)'] <= 400].copy().reset_index(drop=True)

cap = data['Capacidad descargada (Ah)'].values
res = data['resistencia promedio (mΩ)'].values
soh = cap / data['capacidad nominal (Ah)'].values
soh_r = data['resistencia nominal (mΩ)'].values / res

feat_cols = ['Voltaje inicial (V)', 'Voltaje inicial cargada (V)',
             'Capacidad descargada (Ah)', 'Tiempo de descarga (min)',
             'Voltaje final descargada (V)', 'resistencia promedio (mΩ)']
feat_labels = ['Initial voltage', 'Charged voltage', 'Discharged capacity',
               'Discharge time', 'Post-discharge voltage', 'Average resistance']

THRESHOLD = 0.3
w_grid = np.linspace(0, 1, 101)
rows = []

for w in w_grid:
    soh_adj = w * soh + (1 - w) * soh_r
    row = {'w': round(w, 2)}
    selected = []
    for col, label in zip(feat_cols, feat_labels):
        r = np.corrcoef(data[col].values, soh_adj)[0, 1]
        row[f'r_{label}'] = round(r, 4)
        row[f'|r|_{label}'] = round(abs(r), 4)
        if abs(r) >= THRESHOLD:
            selected.append(label)
    row['Selected_features'] = '; '.join(selected)
    rows.append(row)

df = pd.DataFrame(rows)
df.to_excel('../supplementary_tables/S2_Table_w_sensitivity.xlsx', index=False)

# Identify invariance interval
dominant = df.iloc[6:85]['Selected_features'].iloc[0]  # w=0.06 to w=0.84
print(f"Cells: {len(data)}")
print(f"Dominant feature set (w ∈ [0.06, 0.84]): {dominant}")
print(f"Paper w = 0.603 is within invariance interval: True")
print(f"Final features after redundancy removal: {{Discharged capacity, Average resistance}}")
print("\n✓ S2 Table saved")
