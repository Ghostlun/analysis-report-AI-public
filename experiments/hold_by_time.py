import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from kalshi_lib import *
markets, _ = load_markets()
for m in markets: add_features(m)
START = 420
def leader_price(m):
    yes, no = m.ya, m.na
    ld = np.where(np.isfinite(yes) & np.isfinite(no), np.where(yes > no, 1, np.where(no > yes, -1, 0)),
                  np.where(np.isfinite(yes) & (yes >= 0.5), 1, np.where(np.isfinite(no) & (no >= 0.5), -1, 0)))
    return ld
def leader_btc(m):
    return np.where(np.isfinite(m.diff), np.sign(m.diff), 0).astype(int)
def analyse(sel, getter, label):
    rows = []; settle_first = []
    for m in sel:
        ld = getter(m); idx = [i for i in range(len(m.sec)) if m.sec[i] <= START]
        if not idx: continue
        last_i = idx[-1]
        last = ld[last_i]
        # earliest time after which leader never changes through last snapshot
        stable_from = None
        for i in reversed(idx):
            if ld[i] == last and last != 0: stable_from = m.sec[i]
            else: break
        settle_first.append(stable_from)
        for i in idx:
            b = int(round(m.sec[i] / 15.0) * 15)
            if ld[i] == 0: continue
            win = (ld[i] == 1) == bool(m.result)
            same = ld[i] == last
            rows.append((b, win, same))
    d = pd.DataFrame(rows, columns=["sec", "wins_official", "same_as_last"])
    t = d.groupby("sec").agg(n=("wins_official", "size"), win=("wins_official", "mean"), same_as_last=("same_as_last", "mean"))
    print("\n###", label, "markets", len(sel))
    print(t.iloc[::-1].iloc[::2].round(3).to_string())  # every 30s for brevity
    sf = pd.Series([s for s in settle_first if s is not None])
    print("leader stays unchanged from X sec to last snapshot (never flips after): quantiles of X (sec):")
    print(sf.quantile([.1, .25, .5, .75, .9]).round(0).to_dict(), " ; share already stable at 420s:", round((sf >= 405).mean(), 3))
ref = [m for m in markets if m.ref_ok and m.result is not None]
allm = [m for m in markets if m.result is not None]
analyse(allm, leader_price, "ASK-favoured side (higher ask), all settled markets")
analyse(ref, leader_btc, "BTC-favoured side (BRTI vs strike), BRTI markets")
