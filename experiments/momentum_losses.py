import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
from kalshi_strats import *
markets, _ = load_markets()
for m in markets: add_features(m)
ms = [m for m in markets if m.ref_ok and m.result is not None]
by = {m.ticker: m for m in ms}
SIG = 4.275
tr, _ = run_strategy(ms, baseline_momentum(), "S1_project")
rows = []
for t in tr:
    m = by[t.ticker]; i = int(np.argmin(np.abs(m.sec - t.entry_sec))); ft = m.feat
    prev = ft["ask"][i - 1] if i > 0 else np.nan
    rows.append(dict(tk=t.ticker, day=t.day, hour=t.close.hour, lose=not t.held_win, pnl=t.pnl, sec=t.entry_sec, ask=ft["ask"][i],
                     path="momentum(<.95)" if ft["ask"][i] < 0.95 else "standard(>=.95)", dist=ft["dist"][i],
                     z=ft["dist"][i] / (SIG * np.sqrt(max(t.entry_sec, 1))), move60=ft["move60"][i], stable=bool(ft["stable60"][i]),
                     ask_jump=ft["ask"][i] - prev if np.isfinite(prev) else np.nan, slope60=ft["slope60"][i],
                     final_dist=m.diff[-1] * ft["side"][i]))
d = pd.DataFrame(rows)
print("trades", len(d), "losses", int(d.lose.sum()), "loss rate", round(d.lose.mean(), 3), "| total loss $", round(d[d.lose].pnl.sum(), 2), "total win $", round(d[~d.lose].pnl.sum(), 2))
def grp(col, bins=None, labels=None):
    x = d.copy()
    if bins is not None: x[col + "_b"] = pd.cut(x[col], bins, labels=labels); col = col + "_b"
    g = x.groupby(col, observed=True).agg(n=("lose", "size"), losses=("lose", "sum"), loss_rate=("lose", "mean"), pnl=("pnl", "sum")).round(3)
    print("\n--", col); print(g.to_string())
grp("path"); grp("sec", [0, 60, 120, 180, 240, 300]); grp("ask", [0.9, 0.93, 0.95, 0.97, 0.99])
grp("dist", [-1e9, 10, 25, 50, 100, 1e9]); grp("z", [-1, 0.5, 1, 1.5, 2.5, 1e9]); grp("stable"); grp("move60", [-1e9, 0, 10, 30, 1e9])
grp("hour", [-1, 5, 11, 17, 23]); grp("ask_jump", [-1, -0.03, 0.0, 0.03, 1])
print("\nLOSING trades:"); print(d[d.lose][["tk", "hour", "sec", "ask", "path", "dist", "z", "move60", "stable", "ask_jump", "final_dist", "pnl"]].round(2).to_string(index=False))
