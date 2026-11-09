# Fit Q(n) = Q0 * (1 - a * n**b) to the mean capacity curves (log-linear fit on the fade term)
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(7, 3), dpi=110, sharey=True)
for ax, f in zip(axes, ["data/cycling_baseline.csv", "data/cycling_additive.csv"]):
    m = pd.read_csv(f).groupby("cycle").capacity_mAh_g.mean()
    n = m.index.values.astype(float)
    q0 = m.iloc[:5].mean()
    fade = np.clip(1 - m.values / q0, 1e-6, None)
    keep = n > 20
    b, log_a = np.polyfit(np.log(n[keep]), np.log(fade[keep]), 1)
    pred = q0 * (1 - np.exp(log_a) * n ** b)
    ax.scatter(n, m.values - pred, s=2)
    ax.set_title(f.split("_")[1].replace(".csv", "") + f"  b={b:.2f}")
fig.savefig("figures/fit_residuals.png")
