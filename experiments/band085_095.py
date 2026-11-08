import numpy as np, pandas as pd, sys, itertools
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
from kalshi_strats import *
pd.set_option("display.width", 250)
markets, _ = load_markets()
for m in markets: add_features(m)
ms = [m for m in markets if m.ref_ok and m.result is not None]
CUT = pd.Timestamp("2026-10-27", tz="UTC")
dev = [m for m in ms if m.close < CUT]; val = [m for m in ms if m.close >= CUT]
# 1) cell view: BTC-favoured side, ask in [.85,.95]; per snapshot (correlated) -> net edge per contract after fee+0.01
rows = []
for m in ms:
    ft = m.feat
    for i in range(len(m.sec)):
        a = ft["ask"][i]
        if 30 <= m.sec[i] <= 300 and ft["side"][i] != 0 and np.isfinite(a) and 0.85 <= a <= 0.95:
            p = min(a + 0.01, 0.99); cost = p + 0.07 * p * (1 - p)
            win = (ft["side"][i] == 1) == bool(m.result)
            rows.append((m.ticker, m.sec[i], ft["dist"][i], a, cost, win))
d = pd.DataFrame(rows, columns=["tk", "sec", "dist", "ask", "cost", "win"])
d["edge"] = d.win.astype(float) - d.cost
d["tb"] = pd.cut(d.sec, [0, 60, 120, 180, 240, 300], labels=["30-60", "60-120", "120-180", "180-240", "240-300"])
d["db"] = pd.cut(d.dist, [-1, 25, 50, 75, 100, 150, 1e9], labels=["<25", "25-50", "50-75", "75-100", "100-150", "150+"])
print("avg edge per contract after fee+slip (win - cost), BTC side, ask .85-.95")
print(d.pivot_table(index="db", columns="tb", values="edge", aggfunc="mean", observed=True).round(3).to_string())
print("win rate"); print(d.pivot_table(index="db", columns="tb", values="win", aggfunc="mean", observed=True).round(3).to_string())
print("distinct markets"); print(d.pivot_table(index="db", columns="tb", values="tk", aggfunc="nunique", observed=True).to_string())
# 2) strategy view: first qualifying snapshot, dev vs val
def line(sel, fn, scen):
    tr, _ = run_strategy(sel, fn, scen)
    if not tr: return "n=0"
    s = summarize(tr, len(sel), boot=1000)
    return f"n={s['trades']:3d} win={s['settle_win_rate']:.3f} BE={s['breakeven_wr']:.3f} ROI={s['roi']*100:+6.2f}% [{s['roi_ci'][0]*100:+.0f},{s['roi_ci'][1]*100:+.0f}]"
print("\nstrategy: first snapshot in window with ask .85-.95 on BTC side")
for t_hi, t_lo, dm in itertools.product([300, 240, 180], [30, 60], [0, 50, 75, 100, 125]):
    fn = rule(t_hi, t_lo=t_lo, a_lo=0.85, a_hi=0.95, dist_min=dm)
    print(f"t {t_lo}-{t_hi} dist>={dm:3d} | dev {line(dev, fn, 'S1_project')} | val {line(val, fn, 'S1_project')} | all S2 {line(ms, fn, 'S2_delay15s')}")
print("\nz-score version")
for z in (1.0, 1.25, 1.5, 2.0):
    fn = rule(300, t_lo=30, a_lo=0.85, a_hi=0.95, z_min=z, sigma=4.275)
    print(f"z>={z} | dev {line(dev, fn, 'S1_project')} | val {line(val, fn, 'S1_project')} | all S2 {line(ms, fn, 'S2_delay15s')}")
