import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

eis = pd.read_csv("data/impedance.csv")
fig, ax = plt.subplots(figsize=(4.5, 4), dpi=150)
for (el, cyc), g in eis.groupby(["electrolyte", "cycle"]):
    ax.plot(g.z_real_ohm, -g.z_imag_ohm, marker="o", ms=2, lw=1, label=f"{el}, cycle {cyc}")
ax.set_xlabel("Z' (Ω)"); ax.set_ylabel("-Z'' (Ω)"); ax.set_aspect("equal"); ax.legend(fontsize=7, frameon=False)
fig.tight_layout(); fig.savefig("figures/nyquist.png")
