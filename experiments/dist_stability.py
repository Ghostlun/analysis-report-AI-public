import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
markets, _ = load_markets()
ref = [m for m in markets if m.ref_ok and m.result is not None]
rows = []
for m in ref:
    for i in range(len(m.sec)):
        if 30 <= m.sec[i] <= 420 and np.isfinite(m.diff[i]) and m.diff[i] != 0:
            rows.append((m.ticker, m.sec[i], abs(m.diff[i]), (m.diff[i] > 0) == bool(m.result)))
d = pd.DataFrame(rows, columns=["tk", "sec", "dist", "ok"])
d["tb"] = pd.cut(d.sec, [0, 60, 120, 180, 240, 300, 420], labels=["30-60", "60-120", "120-180", "180-240", "240-300", "300-420"])
d["db"] = pd.cut(d.dist, [0, 10, 25, 50, 75, 100, 150, 200, 1e9], labels=["<10", "10-25", "25-50", "50-75", "75-100", "100-150", "150-200", "200+"])
w = d.pivot_table(index="db", columns="tb", values="ok", aggfunc="mean", observed=True).round(3)
n = d.pivot_table(index="db", columns="tb", values="tk", aggfunc="nunique", observed=True)
print("win rate (BTC side = official result)"); print(w.to_string())
print("distinct markets"); print(n.to_string())
