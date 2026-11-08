import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
from kalshi_strats import *
markets, _ = load_markets()
for m in markets: add_features(m)
ms = [m for m in markets if m.ref_ok and m.result is not None]
CUT = pd.Timestamp("2026-10-27", tz="UTC")
dev = [m for m in ms if m.close < CUT]; val = [m for m in ms if m.close >= CUT]
SIG = 4.275
def line(name, sel, fn, scen):
    tr, _ = run_strategy(sel, fn, scen)
    if not tr: return f"{name:8s} n=0"
    s = summarize(tr, len(sel), boot=2000)
    return (f"{name:5s} trades={s['trades']:3d} win={s['settle_win_rate']:.3f} BE={s['breakeven_wr']:.3f} price={s['avg_price']:.3f} "
            f"net={s['net']:+6.2f} ROI={s['roi']*100:+6.2f}% CI=[{s['roi_ci'][0]*100:+.1f},{s['roi_ci'][1]*100:+.1f}]")
for lo, hi in ((0.80, 0.90), (0.83, 0.88), (0.90, 0.95), (0.95, 0.99)):
    for z in (0.0, 0.5, 1.0, 1.5):
        fn = rule(300, a_lo=lo, a_hi=hi, z_min=z, sigma=SIG)
        print(f"\nask {lo}-{hi} z>={z}")
        for scen in ("S1_project", "S2_delay15s"):
            print(f"  {scen:11s} ALL ", line("all", ms, fn, scen))
            print(f"  {scen:11s} dev ", line("dev", dev, fn, scen))
            print(f"  {scen:11s} val ", line("val", val, fn, scen))
