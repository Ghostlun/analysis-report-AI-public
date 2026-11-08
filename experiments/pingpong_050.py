import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
from kalshi_strats import *
markets, _ = load_markets()
for m in markets: add_features(m)
ms = [m for m in markets if m.ref_ok and m.result is not None]
def band(lo, hi, side_mode, t_hi=420, t_lo=60):
    def f(m):
        ft = m.feat
        for i in range(len(m.sec)):
            if not (t_lo <= m.sec[i] <= t_hi): continue
            for s, a in ((1, m.ya[i]), (-1, m.na[i])):
                if not (np.isfinite(a) and lo <= a <= hi): continue
                if side_mode == "btc" and ft["side"][i] != s: continue
                return i, s
        return None
    return f
def show(name, fn, ex, scen):
    tr, _ = run_strategy(ms, fn, scen, ex)
    s = summarize(tr, len(ms), boot=2000)
    print(f"{name:42s} {scen:11s} trades={s['trades']:3d} win(settle)={s['settle_win_rate']:.3f} early_exits={s['early_exits']:3d} "
          f"net={s['net']:+7.2f} spend={s['spend']:7.1f} ROI={s['roi']*100:+6.2f}% CI=[{s['roi_ci'][0]*100:+.1f},{s['roi_ci'][1]*100:+.1f}] DD={s['max_dd']:.1f}")
for scen in ("S0_quoted", "S1_project", "S2_delay15s"):
    for sm in ("any", "btc"):
        fn = band(0.45, 0.55, sm)
        show(f"ask .45-.55 [{sm}] hold", fn, None, scen)
        show(f"ask .45-.55 [{sm}] sell bid>=.60", fn, exit_rule(tp=0.60), scen)
        show(f"ask .45-.55 [{sm}] sell bid>=.60 / stop -.10", fn, exit_rule(tp=0.60, sl_drop=0.10), scen)
        show(f"ask .45-.55 [{sm}] sell bid>=.70 / stop -.15", fn, exit_rule(tp=0.70, sl_drop=0.15), scen)
    print()
