"""Capacity fade of baseline vs. additive electrolyte (NMC811 | graphite coin cells, C/2, 25 C)."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

base = pd.read_csv("data/cycling_baseline.csv")
add = pd.read_csv("data/cycling_additive.csv")

def retention(df, cycle):
    first = df.groupby("cell").capacity_mAh_g.first()
    at = df[df.cycle == cycle].set_index("cell").capacity_mAh_g
    return (at / first * 100)

lines = []
for name, df in [("baseline", base), ("additive", add)]:
    r = retention(df, 500)
    lines.append(f"{name}: retention@500 = {r.mean():.1f} +/- {r.std():.1f} % (n={len(r)} cells)")
    lines.append(f"{name}: mean CE (cycles 10-500) = {df[df.cycle >= 10].coulombic_eff.mean():.3f} %")
fade_b = 100 - retention(base, 500).mean()
fade_a = 100 - retention(add, 500).mean()
lines.append(f"relative reduction in capacity fade = {(1 - fade_a / fade_b) * 100:.1f} %")
open("results/summary_stats.txt", "w").write("\n".join(lines) + "\n")

fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
for name, df, c in [("Baseline", base, "#888"), ("+2% additive", add, "#0f5c5c")]:
    m = df.groupby("cycle").capacity_mAh_g.agg(["mean", "std"])
    ax.plot(m.index, m["mean"], color=c, label=name)
    ax.fill_between(m.index, m["mean"] - m["std"], m["mean"] + m["std"], color=c, alpha=.2)
ax.set_xlabel("Cycle number"); ax.set_ylabel("Discharge capacity (mAh g$^{-1}$)")
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig("figures/capacity_fade.png")
