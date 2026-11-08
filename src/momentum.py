"""Momentum v1 / v2 analysis. Offline and read-only: no network, no orders, no bot code imported.

Two clearly separated parts:
  ACTUAL     - what the live bot really did (data/raw/live_orders_*.csv).
  SIMULATED  - replays of rules on the 15 s market snapshots (data/raw/KXBTC15M_all.csv).
Every function returns DataFrames (or dicts of them); nothing prints, so it works from run.py and the notebook.
"""
from functools import lru_cache
from math import erf, sqrt

import numpy as np
import pandas as pd

from paths import MARKET_CSV, ORDERS_CSV, OUT_ACTUAL, OUT_SIM

STRATEGY = "five_minute_momentum_v1"
FEE_RATE = 0.07
N_CONTRACTS = 5                                   # replay size; live size varied 4-8 ($5 budget default)
SPLIT = pd.Timestamp("2026-10-27T00:00:00Z")      # dev = before, test = on/after (first snapshot of each market)
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
FILTERS = {                                       # the three components of the dev-selected v2
    "standard-only": {"mode": "std_only"},
    "z>=1.5": {"zmin": 1.5},
    "ask<=0.97": {"maxp": 0.97},
}


# ============================================================ loading
@lru_cache(maxsize=None)
def load_market():
    d = pd.read_csv(MARKET_CSV)
    d["ts"] = pd.to_datetime(d.collected_at_utc, utc=True, format="ISO8601")
    d["close"] = pd.to_datetime(d.close_time, utc=True)
    d["sec"] = d.seconds_until_close
    # official_settlement_result is only used as the outcome label, never as a feature
    d = d[d.reference_price_usd.notna() & d.official_settlement_result.isin(["yes", "no"])]
    d["diff"] = d.reference_price_usd - d.floor_strike
    return d.sort_values(["ticker", "ts"]).reset_index(drop=True)


def load_orders(momentum_only=True):
    o = pd.read_csv(ORDERS_CSV)
    o["t"] = pd.to_datetime(o.intended_at, utc=True, format="ISO8601")
    return o[o.strategy_id == STRATEGY].copy() if momentum_only else o


def fee(p, n=1):
    return FEE_RATE * n * p * (1 - p)


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - a) / den, (c + a) / den)


# ============================================================ features (only data at/before the decision row)
def features(g, i):
    h = g.iloc[: i + 1]
    ref = h.reference_price_usd.values
    dif = h["diff"].values
    sec = h.sec.values[-1]
    f = {"sec": sec, "diff": dif[-1]}
    steps = np.diff(ref)
    f["sigma15"] = steps[-20:].std(ddof=1) if len(steps) >= 5 else np.nan  # last ~5 min of 15 s changes
    f["z"] = abs(dif[-1]) / (f["sigma15"] * np.sqrt(max(sec, 1.0) / 15.0)) if f["sigma15"] and f["sigma15"] > 0 else np.nan
    sign = np.sign(dif[-1])
    f["persist"] = 0  # consecutive snapshots (ending now) on the same side of strike
    for v in dif[::-1]:
        if np.sign(v) == sign and sign != 0:
            f["persist"] += 1
        else:
            break
    f["toward"] = (sign * (dif[-1] - dif[-5])) if len(dif) >= 5 else np.nan  # last 60 s move in signal direction
    f["ref_range_5m"] = ref[-20:].max() - ref[-20:].min()
    return f


def side_ask(row, side):
    return row.yes_ask_usd if side == "yes" else row.no_ask_usd


# ============================================================ SIMULATED: v1 rule replay
def v1_signal(g, i):
    """Replicates evaluate_five_minute_direction + evaluate_momentum_entry on 15 s snapshots."""
    r = g.iloc[i]
    if r.sec > 300 or r.sec < 20 or r["diff"] == 0:
        return None
    side = "yes" if r["diff"] > 0 else "no"
    cur = side_ask(r, side)
    if pd.isna(cur):
        return None
    if cur >= 0.95:
        return side, "standard", cur
    if cur < 0.90:
        return None
    col = "yes_ask_usd" if side == "yes" else "no_ask_usd"
    ts = (g.ts - EPOCH).dt.total_seconds().values
    now = ts[i]

    def ref_pt(lb):
        wanted = now - lb
        idx = np.where((ts <= wanted) & g[col].notna().values)[0]
        idx = idx[idx <= i]
        if len(idx) == 0 or wanted - ts[idx[-1]] > 20:
            return None
        return ts[idx[-1]], g[col].values[idx[-1]]

    s, l = ref_pt(30), ref_pt(60)
    if s is None or l is None:
        return None
    ss, sl = (cur - s[1]) / (now - s[0]), (cur - l[1]) / (now - l[0])
    if ss <= 0 or sl <= 0 or ss < 0.8 * sl:
        return None
    if not (0 <= (0.95 - cur) / sl <= min(60, r.sec)):
        return None
    return side, "early", cur


def candidates(d):
    """Every v1 signal (market, snapshot) with its features and next-snapshot ask, computed once."""
    rows = []
    for tk, g in d.groupby("ticker", sort=False):
        g = g.reset_index(drop=True)
        res = g.official_settlement_result.iloc[0]
        for i in range(len(g)):
            sig = v1_signal(g, i)
            if sig is None:
                continue
            side, mode, cur = sig
            f = features(g, i)
            nxt = (side_ask(g.iloc[i + 1], side), g.sec.iloc[i + 1]) if i + 1 < len(g) else (np.nan, np.nan)
            rows.append({"ticker": tk, "t": g.ts.iloc[i], "side": side, "mode": mode, "cur": cur, "sec": f["sec"],
                         "z": f["z"], "persist": f["persist"], "next_ask": nxt[0], "next_sec": nxt[1], "win": res == side})
    return pd.DataFrame(rows)


def replay(C, v2=None, delay=0, slip=0.0):
    """One entry per market: the first candidate that passes the (optional) v2 filters.
    delay=1: fill at the next snapshot (skipped if it moved > 1c). slip: extra price paid."""
    c = C
    if v2 is not None:
        m = pd.Series(True, index=c.index)
        if v2.get("mode") == "std_only":
            m &= c["mode"] == "standard"
        m &= c.z.fillna(-1) >= v2.get("zmin", 0)
        m &= c.persist >= v2.get("persist", 1)
        m &= c.cur <= v2.get("maxp", 1.0)
        c = c[m]
    c = c.groupby("ticker", sort=False).head(1).copy()
    if delay:
        c = c[c.next_ask.notna() & (c.next_sec >= 20) & (c.next_ask <= c.cur + 0.01)]
        p = c.next_ask
    else:
        p = c.cur
    c["price"] = np.minimum(p + slip, 0.99)
    c["pnl"] = N_CONTRACTS * (c.win.astype(float) - c.price) - FEE_RATE * N_CONTRACTS * c.price * (1 - c.price)
    return c


def summarize(df, label=""):
    if len(df) == 0:
        return {"label": label, "n": 0}
    df = df.sort_values("t")
    cum = df.pnl.cumsum()
    wins = df.win.sum()
    lo, hi = wilson(wins, len(df))
    boot = np.random.default_rng(0).choice(df.pnl.values, (4000, len(df))).sum(axis=1)
    return {"label": label, "n": len(df), "wins": int(wins), "wr": wins / len(df), "wr_lo": lo, "avg_px": df.price.mean(),
            "net": df.pnl.sum(), "net_lo": np.percentile(boot, 2.5), "net_hi": np.percentile(boot, 97.5),
            "maxdd": (cum.cummax().clip(lower=0) - cum).max()}


@lru_cache(maxsize=None)
def sim_candidates():
    """(dev, test) candidate tables. Dev = markets first seen before SPLIT, test = on/after (untouched for selection)."""
    d = load_market()
    mk = d.groupby("ticker").ts.min()
    dev, test = mk[mk < SPLIT].index, mk[mk >= SPLIT].index
    return candidates(d[d.ticker.isin(dev)]), candidates(d[d.ticker.isin(test)])


SCENARIOS = (("ideal", {}), ("slip+0.01", {"slip": 0.01}), ("delay15s", {"delay": 1}))


def dev_grid():
    """Threshold grid scored on the DEV period only (slip+0.01). Writes outputs/simulated/momentum_v2_dev_grid.csv."""
    Cd, _ = sim_candidates()
    rows = []
    for mode in ("all", "std_only"):
        for zmin in (0, 1, 1.5, 2, 2.5, 3):
            for persist in (1, 2, 3, 4):
                for maxp in (0.97, 0.98, 0.99, 1.0):
                    v = {"mode": mode, "zmin": zmin, "persist": persist, "maxp": maxp}
                    s = summarize(replay(Cd, v, slip=0.01))
                    rows.append({**v, **{k: s.get(k) for k in ("n", "wins", "net", "net_lo", "maxdd")}})
    G = pd.DataFrame(rows)
    G.to_csv(OUT_SIM / "momentum_v2_dev_grid.csv", index=False)
    return G


@lru_cache(maxsize=None)
def chosen_v2():
    """Best dev-grid rule with >= 60 trades; chosen without looking at the test period."""
    G = dev_grid()
    best = G[G.n >= 60].sort_values("net", ascending=False).iloc[0]
    return tuple({"mode": best["mode"], "zmin": best.zmin, "persist": int(best.persist), "maxp": best.maxp}.items())


def v1_vs_v2():
    """SIMULATED v1 vs dev-selected v2, per period and fill scenario (N=5 contracts)."""
    Cd, Ct = sim_candidates()
    v2 = dict(chosen_v2())
    rows = []
    for period, C in (("dev", Cd), ("test", Ct)):
        for rule, v in (("v1", None), ("v2", v2)):
            for sc, kw in SCENARIOS:
                rows.append({"period": period, "rule": rule, "scenario": sc, **summarize(replay(C, v, **kw))})
    return pd.DataFrame(rows).drop(columns=["label"])


def paired_diff():
    """Test period, slip+0.01: v2 - v1 net P&L over identical markets, with a bootstrap interval."""
    _, Ct = sim_candidates()
    r1, r2 = replay(Ct, None, slip=0.01), replay(Ct, dict(chosen_v2()), slip=0.01)
    j = r1.set_index("ticker").pnl.to_frame("v1").join(r2.set_index("ticker").pnl.to_frame("v2")).fillna(0)
    dif = (j.v2 - j.v1).values
    lo, hi = np.percentile(np.random.default_rng(1).choice(dif, (4000, len(dif))).sum(axis=1), [2.5, 97.5])
    return pd.DataFrame([{"v1_markets": len(r1), "v2_markets": len(r2), "diff_net": dif.sum(), "ci_lo": lo, "ci_hi": hi}])


def filter_impact(period="test", scenario="slip+0.01"):
    """How each filter changes trade count and P&L versus v1 on identical markets.
    Rows: each filter alone, filters added one by one, and the full v2 with one filter removed.
    skipped_* = v1 trades on markets the rule no longer enters; retimed = same market, different entry snapshot."""
    Cd, Ct = sim_candidates()
    C = Cd if period == "dev" else Ct
    kw = dict(SCENARIOS)[scenario]
    base = replay(C, None, **kw).set_index("ticker")
    names = list(FILTERS)
    rules = [("v1 (no filters)", {})]
    rules += [(f"only {n}", FILTERS[n]) for n in names]
    cum = {}
    for n in names:
        cum = {**cum, **FILTERS[n]}
        rules.append((f"+ {n} (cumulative)", dict(cum)))
    for n in names:
        rest = {k: v for m in names if m != n for k, v in FILTERS[m].items()}
        rules.append((f"v2 without {n}", rest))
    out = []
    for label, v in rules:
        r = replay(C, v if v else None, **kw).set_index("ticker")
        s = summarize(r.reset_index())
        skipped = base.index.difference(r.index)
        both = base.index.intersection(r.index)
        retimed = both[(base.loc[both, "t"] != r.loc[both, "t"]).values]
        out.append({"rule": label, "n": s["n"], "d_n": s["n"] - len(base), "losses": int((~r.win).sum()),
                    "net": s["net"], "d_net": s["net"] - base.pnl.sum(), "maxdd": s["maxdd"],
                    "skipped_n": len(skipped), "skipped_losses": int((~base.loc[skipped, "win"]).sum()),
                    "skipped_v1_net": base.loc[skipped, "pnl"].sum(), "retimed_n": len(retimed),
                    "retimed_d_net": (r.loc[retimed, "pnl"] - base.loc[retimed, "pnl"]).sum()})
    return pd.DataFrame(out)


def trade_cumulative(period="test", scenario="slip+0.01"):
    """Cumulative simulated P&L by entry time for v1 and v2 (for plotting)."""
    Cd, Ct = sim_candidates()
    C = Cd if period == "dev" else Ct
    kw = dict(SCENARIOS)[scenario]
    res = {}
    for rule, v in (("v1", None), ("v2", dict(chosen_v2()))):
        r = replay(C, v, **kw).sort_values("t")
        res[rule] = pd.Series(r.pnl.cumsum().values, index=r.t.values)
    return res


def fidelity():
    """SIMULATED vs ACTUAL sanity check: does the snapshot replay of v1 pick the same markets/side/mode as live?"""
    live = load_orders()
    live = live[live.status == "settled"].set_index("market_ticker")
    d = load_market()
    dd = d[d.ticker.isin(d[d.ts >= pd.Timestamp("2026-10-28T00:00:00Z")].ticker.unique())]
    rp = replay(candidates(dd)).set_index("ticker")
    both = rp.index.intersection(live.index)
    mm = rp.loc[both, "mode"].map({"standard": "momentum_standard", "early": "momentum_early"}) == live.loc[both, "entry_mode"]
    return pd.DataFrame([{
        "replay_entries": len(rp), "live_settled": len(live), "common": len(both),
        "same_side": (rp.loc[both, "side"] == live.loc[both, "side"]).mean(), "same_mode": mm.mean(),
        "mean_abs_price_diff": (rp.loc[both, "price"] - live.loc[both, "average_fill_price_usd"]).abs().mean(),
        "replay_only": len(rp.index.difference(live.index)), "live_only": len(live.index.difference(rp.index)),
        "replay_pnl_common_N5": rp.loc[both, "pnl"].sum(),
        "live_pnl_common_per5": (live.loc[both, "realized_pnl_usd"] / live.loc[both, "filled_contracts"] * 5).sum()}])


# ============================================================ ACTUAL: live results
def actual_audit():
    """Reconcile the live momentum orders: statuses, fees, P&L identity, per-mode and per-day totals."""
    o = pd.read_csv(ORDERS_CSV)
    m = o[o.strategy_id == STRATEGY]
    s = m[m.status == "settled"]
    calc = s.filled_contracts * (s.settlement_result == "won") - s.fill_cost_usd - s.fees_usd
    s = s.assign(day=pd.to_datetime(s.intended_at, utc=True, format="ISO8601").dt.date)
    by = lambda k: s.groupby(k).agg(n=("id", "size"), wins=("settlement_result", lambda x: (x == "won").sum()),
                                    losses=("settlement_result", lambda x: (x == "lost").sum()),
                                    pnl=("realized_pnl_usd", "sum"), fees=("fees_usd", "sum"), avg_fill=("average_fill_price_usd", "mean"))
    return {
        "summary": pd.DataFrame([{"rows_all_strategies": len(o), "rows_momentum": len(m), "settled": len(s),
                                  "net_pnl": s.realized_pnl_usd.sum(), "fees": s.fees_usd.sum(), "cost": s.fill_cost_usd.sum(),
                                  "max_abs_pnl_identity_error": (calc - s.realized_pnl_usd).abs().max(),
                                  "partial_fills": int((s.filled_contracts < s.requested_contracts).sum()),
                                  "dup_tickers": int(m.market_ticker.duplicated().sum()),
                                  "dup_client_ids": int(m.client_order_id.duplicated().sum())}]),
        "strategies_by_status": pd.crosstab(o.strategy_id, o.status),
        "momentum_by_mode_status": pd.crosstab(m.entry_mode, m.status),
        "by_mode": by("entry_mode"), "by_day_utc": by("day"),
        "errors": m.error_code.value_counts().rename("count").to_frame(),
    }


def actual_trades(save=True):
    """One row per settled live momentum trade, with the snapshot state just before the order (reconstructed, not logged)."""
    s = load_orders()
    s = s[s.status == "settled"]
    d = load_market()
    rows = []
    for _, r in s.iterrows():
        g = d[d.ticker == r.market_ticker].reset_index(drop=True)
        if g.empty:
            continue
        k = np.where(g.ts <= r.t)[0]
        if len(k) == 0:
            continue
        i = k[-1]
        row = g.iloc[i]
        f = features(g, i)
        sgn = 1 if r.side == "yes" else -1
        after = g[g.ts > r.t]
        ask = side_ask(row, r.side)
        bid = row.yes_bid_usd if r.side == "yes" else row.no_bid_usd
        rows.append({"id": r.id, "ticker": r.market_ticker, "t": r.t, "mode": r.entry_mode, "side": r.side,
                     "qty": r.filled_contracts, "fill": r.average_fill_price_usd, "fees": r.fees_usd, "pnl": r.realized_pnl_usd,
                     "result": r.settlement_result, "snap_age": (r.t - row.ts).total_seconds(), "snap_ask": ask,
                     "spread": ask - bid if pd.notna(ask) and pd.notna(bid) else np.nan,
                     "sec": f["sec"] - (r.t - row.ts).total_seconds(), "diff": f["diff"], "sdiff": sgn * f["diff"],
                     "sigma15": f["sigma15"], "z": f["z"], "persist": f["persist"],
                     "toward60": f["toward"] * 1.0 if pd.notna(f["toward"]) else np.nan, "range5m": f["ref_range_5m"],
                     "worst_after": (sgn * after["diff"]).min() if len(after) else np.nan,  # < 0 = BRTI crossed the strike
                     "final_diff": sgn * g["diff"].iloc[-1], "official": g.official_settlement_result.iloc[0],
                     "official_px": g.official_final_btc_price_usd.iloc[0], "strike": g.floor_strike.iloc[0]})
    t = pd.DataFrame(rows)
    t["slip_vs_snap"] = t.fill - t.snap_ask  # live fill minus last collector ask
    if save:
        t.to_csv(OUT_ACTUAL / "momentum_trade_features.csv", index=False)
    return t


def actual_losses(t=None):
    """The losing live trades with what the strategy could see, plus a won-vs-lost feature comparison."""
    t = actual_trades() if t is None else t
    L, W = t[t.result == "lost"].sort_values("t"), t[t.result == "won"]
    cols = ["sec", "sdiff", "sigma15", "z", "persist", "toward60", "range5m", "spread", "fill"]
    cmp = pd.DataFrame({"lost_median": L[cols].median(), "won_median": W[cols].median(),
                        "won_p10": W[cols].quantile(.1), "won_p25": W[cols].quantile(.25)})
    return {"losses": L[["id", "ticker", "t", "sec", "side", "mode", "fill", "qty", "fees", "pnl", "snap_ask", "snap_age"]],
            "loss_features": L[["id", "sdiff", "sigma15", "z", "persist", "toward60", "range5m", "spread", "worst_after",
                                "final_diff", "official_px", "strike"]].round(3),
            "won_vs_lost": cmp.round(3)}


def actual_buckets(t=None):
    """Live results by price paid, z and seconds remaining (post-hoc buckets: descriptive, not a test)."""
    t = actual_trades() if t is None else t
    agg = dict(n=("id", "size"), losses=("result", lambda x: (x == "lost").sum()), pnl=("pnl", "sum"))
    out = {}
    for name, col, bins in (("by_price", "fill", [0.8, .9, .93, .95, .97, .98, 1.0]), ("by_z", "z", [0, 1, 1.5, 2, 3, 5, 100]),
                            ("by_seconds_left", "sec", [0, 60, 120, 180, 240, 300])):
        out[name] = t.groupby(pd.cut(t[col], bins), observed=True).agg(**agg)
    return out


def actual_calibration(t=None):
    """Gaussian win probability implied by z versus the price actually paid, live fills."""
    t = actual_trades() if t is None else t
    t = t.assign(phi=t.z.apply(lambda z: 0.5 * (1 + erf(z / sqrt(2))) if z == z else np.nan), won=t.result == "won")
    by = t.groupby(pd.cut(t.z, [0, 1, 1.5, 2, 5]), observed=True).agg(
        n=("id", "size"), implied_p=("phi", "mean"), avg_fill=("fill", "mean"), win_rate=("won", "mean"), pnl=("pnl", "sum"))
    return {"overall": pd.DataFrame([{"implied_p": t.phi.mean(), "avg_fill": t.fill.mean(), "win_rate": t.won.mean()}]),
            "by_z": by.round(3), "losses": t[~t.won][["id", "z", "phi", "fill"]].round(3)}


# ============================================================ charts
def plot_actual_cumulative(t=None):
    import matplotlib.pyplot as plt
    t = (actual_trades() if t is None else t).sort_values("t")
    ax = t.set_index("t").pnl.cumsum().plot(drawstyle="steps-post", figsize=(9, 3.5), title="ACTUAL live momentum_v1: cumulative net P&L ($)")
    lost = t[t.result == "lost"]
    ax.scatter(lost.t, t.pnl.cumsum()[lost.index], color="red", zorder=3, label="losing trade")
    ax.legend()
    plt.show()


def plot_sim_cumulative(period="test"):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 3.5))
    for rule, s in trade_cumulative(period).items():
        ax.step(s.index, s.values, where="post", label=rule)
    ax.set_title(f"SIMULATED ({period} period, N={N_CONTRACTS}, slip+0.01): cumulative net P&L ($)")
    ax.legend()
    plt.show()


def plot_filter_impact(period="test"):
    import matplotlib.pyplot as plt
    f = filter_impact(period)
    f = f[f.rule != "v1 (no filters)"]
    ax = f.set_index("rule").d_net.plot.barh(figsize=(8, 4), title=f"SIMULATED ({period}): change in net P&L vs v1 ($)")
    ax.axvline(0, color="k", lw=.8)
    plt.tight_layout()
    plt.show()


def plot_loss_z(t=None):
    import matplotlib.pyplot as plt
    t = actual_trades() if t is None else t
    fig, ax = plt.subplots(figsize=(8, 3.5))
    for res, c in (("won", "tab:green"), ("lost", "tab:red")):
        x = t[t.result == res]
        ax.scatter(x.z, x.fill, c=c, label=res, alpha=.6)
    ax.axvline(1.5, ls="--", color="gray")
    ax.set_xlabel("z (time-adjusted distance)")
    ax.set_ylabel("fill price")
    ax.set_title("ACTUAL live momentum_v1 trades")
    ax.legend()
    plt.show()
