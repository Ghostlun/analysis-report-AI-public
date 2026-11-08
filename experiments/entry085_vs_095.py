import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
markets, _ = load_markets()
for m in markets: add_features(m)
ms = [m for m in markets if m.ref_ok and m.result is not None]
print("markets", len(ms))

def mom(lo, hi, t_hi=300, t_lo=30):
    def f(m):
        ft = m.feat
        for i in range(len(m.sec)):
            if not (t_lo <= m.sec[i] <= t_hi) or ft["side"][i] == 0: continue
            a = ft["ask"][i]
            if not (np.isfinite(a) and lo <= a <= hi): continue
            s30, s60 = ft["slope30"][i], ft["slope60"][i]
            if not (np.isfinite(s30) and np.isfinite(s60) and s30 > 0 and s60 > 0 and s30 >= 0.8 * s60): continue
            return i, int(ft["side"][i])
        return None
    return f
def plain(lo, hi, t_hi=300, t_lo=30):
    def f(m):
        ft = m.feat
        for i in range(len(m.sec)):
            if not (t_lo <= m.sec[i] <= t_hi) or ft["side"][i] == 0: continue
            a = ft["ask"][i]
            if np.isfinite(a) and lo <= a <= hi: return i, int(ft["side"][i])
        return None
    return f
def show(name, fn, scen="S1_project"):
    tr, _ = run_strategy(ms, fn, scen)
    s = summarize(tr, len(ms), boot=2000)
    print(f"{name:34s} {scen:11s} trades={s['trades']:3d} win={s['settle_win_rate']:.3f} BE={s['breakeven_wr']:.3f} avg_price={s['avg_price']:.3f} "
          f"net={s['net']:+7.2f} spend={s['spend']:7.1f} ROI={s['roi']*100:+6.2f}% CI=[{s['roi_ci'][0]*100:+.1f},{s['roi_ci'][1]*100:+.1f}] DD={s['max_dd']:.1f}")
for scen in ("S1_project", "S2_delay15s"):
    show("momentum ask 0.83-0.88 (~0.85)", mom(0.83, 0.88), scen)
    show("momentum ask 0.80-0.90", mom(0.80, 0.90), scen)
    show("momentum ask 0.90-0.95", mom(0.90, 0.9499), scen)
    show("plain ask >=0.95 (no momentum)", plain(0.95, 0.99), scen)
    show("plain ask 0.83-0.88 (no momentum)", plain(0.83, 0.88), scen)
# same-market comparison: markets where momentum 0.85 entry fires; what would 0.95 entry have done?
f85 = mom(0.83, 0.88); f95 = plain(0.95, 0.99)
a = [m for m in ms if f85(m) is not None]
print("\nsame markets (momentum@0.85 fires):", len(a))
for name, fn in (("enter at ~0.85", f85), ("wait for 0.95", f95)):
    tr, sk = run_strategy(a, fn, "S1_project"); s = summarize(tr, len(a), boot=2000)
    print(f"  {name:16s} trades={s['trades']} win={s['settle_win_rate']:.3f} BE={s['breakeven_wr']:.3f} net={s['net']:+.2f} ROI={s['roi']*100:+.2f}% CI=[{s['roi_ci'][0]*100:+.1f},{s['roi_ci'][1]*100:+.1f}]")
