"""Reproduces every table in KALSHI_STRATEGY_ANALYSIS.md. Run: venv311\\Scripts\\python.exe make_report_tables.py"""
import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
from kalshi_strats import *
markets, df = load_markets()
for m in markets: add_features(m)
ref = [m for m in markets if m.ref_ok and m.result is not None]
CUT = pd.Timestamp("2026-10-27", tz="UTC")
dev = [m for m in ref if m.close < CUT]; val = [m for m in ref if m.close >= CUT]
print("dev", len(dev), "val", len(val), "dev days", sorted({m.day for m in dev}), "val days", sorted({m.day for m in val}))
SIG = 4.275
cands = {
    "BASE 95force (default)": baseline_95force(),
    "BASE price_threshold_v1": baseline_price_threshold(),
    "BASE momentum_v1": baseline_momentum(),
    "BASE direction_v1": baseline_direction(),
    "C1 t<=120 ask<=.90 stable": rule(120, a_hi=0.90, stable=True),
    "C1n t<=120 ask<=.95 stable": rule(120, a_hi=0.95, stable=True),
    "C1n t<=180 ask<=.90 stable": rule(180, a_hi=0.90, stable=True),
    "C2 t<=180 ask<=.90 move60>=0": rule(180, a_hi=0.90, move_min=0.0, stable=True),
    "C2n t<=180 ask<=.99 move60>=0": rule(180, a_hi=0.99, move_min=0.0, stable=True),
    "C2n t<=120 ask<=.90 move60>=0": rule(120, a_hi=0.90, move_min=0.0, stable=True),
    "C3 t<=240 ask<=.99 z>=1.5": rule(240, a_hi=0.99, z_min=1.5, sigma=SIG),
    "C3n t<=180 ask<=.99 z>=1.5": rule(180, a_hi=0.99, z_min=1.5, sigma=SIG),
    "C3n t<=300 ask<=.99 z>=1.5": rule(300, a_hi=0.99, z_min=1.5, sigma=SIG),
    "EARLY t<=300 ask<=.70 BTC-side": rule(300, a_hi=0.70),
    "EARLY t<=300 ask<=.80 BTC-side": rule(300, a_hi=0.80),
}
def line(ms, fn, scen, ex=None):
    tr, sk = run_strategy(ms, fn, scen, ex)
    if not tr: return "n=0"
    s = summarize(tr, len(ms), boot=2000)
    return (f"elig={s['eligible']} trades={s['trades']} skip={s['skipped']} cov={s['trades']/s['eligible']:.0%} win(settle)={s['settle_win_rate']:.3f} "
            f"BE={s['breakeven_wr']:.3f} net={s['net']:+.2f} avg={s['avg']:+.3f} spend={s['spend']:.1f} ROI={s['roi']*100:+.2f}% "
            f"CI=[{s['roi_ci'][0]*100:+.1f},{s['roi_ci'][1]*100:+.1f}] P(ROI<=0)={s['p_roi_le0']:.2f} DD={s['max_dd']:.2f} lose_streak={s['max_lose_streak']} "
            f"days+={s['days_pos']}/{s['days']}")
for name, fn in cands.items():
    print("\n##", name)
    for scen in ("S0_quoted", "S1_project", "S2_delay15s", "S3_delay_worse", "S4_thin_book"):
        print(f"  {scen:15s} DEV  {line(dev, fn, scen)}")
        print(f"  {scen:15s} VAL  {line(val, fn, scen)}")
tr, _ = run_strategy(val, baseline_price_threshold(), "S1_project")
print("\nthreshold val daily:", summarize(tr, len(val), boot=10)["daily"])
tr, _ = run_strategy(val, baseline_95force(), "S1_project")
print("95force val daily:", summarize(tr, len(val), boot=10)["daily"])
# notebook checks
last = [(m.diff[-1] > 0) == bool(m.result) for m in ref if np.isfinite(m.diff[-1])]
print("\nlast-ref vs official agree", sum(last), "of", len(last))
pre = pd.concat([pd.DataFrame({"sec": m.sec, "ya": m.ya, "na": m.na, "res": m.result}) for m in markets])
print("markets with a snapshot <=15s:", sum(1 for m in markets if m.sec.min() <= 15), "<=20s:", sum(1 for m in markets if m.sec.min() <= 20), "of", len(markets))
