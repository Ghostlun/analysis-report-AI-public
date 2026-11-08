import numpy as np, pandas as pd, sys
from scipy.stats import norm, t as tdist
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
markets, _ = load_markets()
for m in markets: add_features(m)
ms = [m for m in markets if m.ref_ok and m.result is not None]
CUT = pd.Timestamp("2026-10-27", tz="UTC")
dev = [m for m in ms if m.close < CUT]; val = [m for m in ms if m.close >= CUT]
SIG = 4.275
def edge_rule(margin, t_hi=300, t_lo=30, nu=None, a_max=0.99, sig=SIG):
    def f(m):
        ft = m.feat
        for i in range(len(m.sec)):
            s = m.sec[i]
            if not (t_lo <= s <= t_hi) or ft["side"][i] == 0: continue
            a = ft["ask"][i]
            if not (np.isfinite(a) and a <= a_max): continue
            z = ft["dist"][i] / (sig * np.sqrt(s))
            p = norm.cdf(z) if nu is None else tdist.cdf(z, nu)
            p_cost = min(a + 0.01, 0.99); cost = p_cost + 0.07 * p_cost * (1 - p_cost)
            if p - cost >= margin: return i, int(ft["side"][i])
        return None
    return f
def line(sel, fn, scen):
    tr, _ = run_strategy(sel, fn, scen)
    if not tr: return "n=0"
    s = summarize(tr, len(sel), boot=1000)
    return f"n={s['trades']:3d} win={s['settle_win_rate']:.3f} BE={s['breakeven_wr']:.3f} price={s['avg_price']:.2f} ROI={s['roi']*100:+6.2f}% [{s['roi_ci'][0]*100:+.0f},{s['roi_ci'][1]*100:+.0f}]"
for nu in (None, 4):
    print("\nmodel:", "normal" if nu is None else f"student-t nu={nu}")
    for margin in (0.0, 0.02, 0.04, 0.06, 0.08, 0.10):
        fn = edge_rule(margin, nu=nu)
        print(f"margin>={margin:.2f} | dev {line(dev, fn, 'S1_project')} | val {line(val, fn, 'S1_project')} | all S2 {line(ms, fn, 'S2_delay15s')}")
