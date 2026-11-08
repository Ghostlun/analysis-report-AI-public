"""Gap rule: for each time-to-close bin, the minimum |% gap| between BTC reference price and strike that was 'safe enough'
(Wilson lower bound of the leader's win rate >= target on dev markets). Buy the side of the gap once the gap is at least
that threshold inside that time bin.   pct = 100*ln(reference_price/floor_strike); pct > 0 -> YES side, pct < 0 -> NO side.

SIMULATED/offline: thresholds are fit on dev, judged on test; the exported JSON is what a bot would load.
"""
import json

import numpy as np
import pandas as pd

import momentum as M
from paths import OUT_SIM

BINS = [15, 60, 120, 180, 240, 300, 420, 600]
GRID = np.round(np.arange(0.01, 0.51, 0.01), 2)


def load_samples():
    d = M.load_market().dropna(subset=["yes_ask_usd", "no_ask_usd", "floor_strike"]).copy()
    d["pct"] = 100 * np.log(d.reference_price_usd / d.floor_strike)
    d["yes"] = (d.official_settlement_result == "yes").astype(int)
    d["ap"] = d.pct.abs()
    d["buy_yes"] = d.pct > 0
    d["win"] = (d.buy_yes == (d.yes == 1)).astype(int)
    d["ask"] = np.where(d.buy_yes, d.yes_ask_usd, d.no_ask_usd)
    first = d.groupby("ticker").ts.transform("min")
    d["period"] = np.where(first < M.SPLIT, "dev", "test")
    d["next_ask"] = d.groupby("ticker").apply(lambda g: pd.Series(np.where(g.buy_yes, g.yes_ask_usd.shift(-1), g.no_ask_usd.shift(-1)),
                                                                   index=g.index), include_groups=False).reset_index(level=0, drop=True)
    d["next_sec"] = d.groupby("ticker").sec.shift(-1)
    d = d[(d.sec >= BINS[0]) & (d.sec <= BINS[-1]) & (d.pct != 0)].copy()
    d["bin"] = pd.cut(d.sec, BINS, labels=False)
    return d


def fit_thresholds(d, target=0.95, min_n=30):
    """Smallest |pct| per time bin whose cumulative win-rate Wilson lower bound >= target (None = never safe enough)."""
    out = []
    for b, g in d.groupby("bin"):
        g = g.sort_values("ts").groupby("ticker").head(1)          # one observation per market per bin
        thr = None
        for x in GRID:
            s = g[g.ap >= x]
            if len(s) < min_n:
                break
            if M.wilson(int(s.win.sum()), len(s))[0] >= target:
                thr = float(x)
                break
        out.append({"sec_lo": BINS[int(b)], "sec_hi": BINS[int(b) + 1], "min_abs_pct": thr})
    return pd.DataFrame(out)


def replay(d, table, slip=0.01, max_price=0.99, delay=0):
    """One entry per market: first snapshot where |pct| >= the threshold of its time bin. delay=1 fills at the next snapshot's ask."""
    thr = {int(i): r.min_abs_pct for i, r in enumerate(table.itertuples()) if r.min_abs_pct is not None and not pd.isna(r.min_abs_pct)}
    c = d[d.bin.map(thr).notna() & (d.ap >= d.bin.map(thr))].sort_values(["ticker", "sec"], ascending=[True, False])
    c = c.groupby("ticker", sort=False).head(1)
    raw = c.ask
    if delay:
        c = c[c.next_ask.notna() & (c.next_sec >= 15)]
        raw = c.next_ask
    price = np.minimum(raw + slip, max_price)
    c = c.assign(price=price)
    c = c[(raw + slip) <= max_price]
    c["pnl"] = c.win - c.price - M.FEE_RATE * c.price * (1 - c.price)
    return c


def run(save=True):
    d = load_samples()
    dev, test = d[d.period == "dev"], d[d.period == "test"]
    rows, tables = [], {}
    for target in (0.90, 0.95, 0.98):
        t = fit_thresholds(dev, target)
        tables[target] = t
        for name, kw in (("immediate", {}), ("delay15s", {"delay": 1})):
            for per, df in (("dev", dev), ("test", test)):
                r = replay(df, t, **kw)
                rows.append({"target_wilson_lb": target, "fill": name, "period": per, "n": len(r),
                             "wr": r.win.mean() if len(r) else np.nan, "avg_price": r.price.mean() if len(r) else np.nan,
                             "ev_per_contract": r.pnl.mean() if len(r) else np.nan,
                             "se": r.pnl.std() / np.sqrt(len(r)) if len(r) > 1 else np.nan,
                             "avg_sec": r.sec.mean() if len(r) else np.nan})
    result = pd.DataFrame(rows)
    final = fit_thresholds(d, 0.95)                               # all markets, for the exported rule
    if save:
        result.to_csv(OUT_SIM / "gap_rule_results.csv", index=False)
        spec = {"rule": "buy YES if pct>0 else NO once abs(pct) >= min_abs_pct for the bin containing seconds-to-close; "
                        "one entry per market; pct=100*ln(reference_price/floor_strike)",
                "target": "Wilson 95% lower bound of leader win rate >= 0.95, all markets in data/raw/KXBTC15M_all.csv",
                "bins": [{"sec_lo": int(r.sec_lo), "sec_hi": int(r.sec_hi),
                          "min_abs_pct": None if pd.isna(r.min_abs_pct) else float(r.min_abs_pct)} for r in final.itertuples()]}
        (OUT_SIM / "gap_rule.json").write_text(json.dumps(spec, indent=2))
    return {"dev-fit thresholds (target 0.95)": tables[0.95], "all-data thresholds exported to gap_rule.json": final,
            "replay (EV per contract after fee + 1c slip)": result}
