"""Pattern/probability model: P(yes) from the % gap between BTC reference price and strike and the recent shape of that gap.

SIMULATED/offline only. Features use log-percentage gap pct = 100*ln(ref/strike), its recent path, and time to close.
Models are fit on dev markets (first seen before momentum.SPLIT) and judged on test markets against the market's own price.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

import momentum as M
from paths import OUT_SIM

LAGS = (2, 4, 8, 12, 20)          # snapshots back (~30/60/120/180/300 s)
SEC_LO, SEC_HI = 30, 600
FEATURES = ["z", "pct", "sec", "sigma"] + [f"d{k}" for k in LAGS]
KNN_FEATURES = ["z", "sec"] + [f"d{k}" for k in LAGS]


def build_samples():
    """One row per snapshot with SEC_LO <= sec <= SEC_HI. Only data up to that snapshot is used for features."""
    d = M.load_market().dropna(subset=["yes_ask_usd", "no_ask_usd", "yes_bid_usd", "no_bid_usd", "floor_strike"])
    first = d.groupby("ticker").ts.min()
    rows = []
    for tk, g in d.groupby("ticker", sort=False):
        if len(g) < 30:
            continue
        pct = 100 * np.log(g.reference_price_usd.values / g.floor_strike.values)
        sec = g.sec.values
        yes = int(g.official_settlement_result.iloc[0] == "yes")
        step = np.diff(pct)
        for i in range(max(LAGS), len(g)):
            if not (SEC_LO <= sec[i] <= SEC_HI):
                continue
            sigma = max(np.std(step[max(0, i - 20):i]), 1e-4)     # % per snapshot, trailing
            row = {"ticker": tk, "period": "dev" if first[tk] < M.SPLIT else "test", "sec": sec[i], "pct": pct[i],
                   "sigma": sigma, "z": pct[i] / (sigma * np.sqrt(max(sec[i], 1) / 15)),
                   "mid": (g.yes_bid_usd.values[i] + g.yes_ask_usd.values[i]) / 2,
                   "ask_yes": g.yes_ask_usd.values[i], "ask_no": g.no_ask_usd.values[i], "y": yes,
                   "next_ask_yes": g.yes_ask_usd.values[i + 1] if i + 1 < len(g) else np.nan,
                   "next_ask_no": g.no_ask_usd.values[i + 1] if i + 1 < len(g) else np.nan,
                   "next_sec": sec[i + 1] if i + 1 < len(g) else np.nan}
            for k in LAGS:
                row[f"d{k}"] = (pct[i] - pct[i - k]) / (sigma * np.sqrt(k))
            rows.append(row)
    return pd.DataFrame(rows)


def fit_models(train):
    scaler = StandardScaler().fit(train[KNN_FEATURES])
    models = {
        "logit": LogisticRegression(max_iter=2000, C=1.0).fit(train[FEATURES], train.y),
        "gbm": HistGradientBoostingClassifier(max_depth=3, max_iter=120, learning_rate=0.05, random_state=0).fit(train[FEATURES], train.y),
        "analog_knn": (scaler, KNeighborsClassifier(n_neighbors=150, weights="distance").fit(scaler.transform(train[KNN_FEATURES]), train.y)),
    }
    return models


def predict(models, df):
    out = df.copy()
    out["p_logit"] = models["logit"].predict_proba(df[FEATURES])[:, 1]
    out["p_gbm"] = models["gbm"].predict_proba(df[FEATURES])[:, 1]
    scaler, knn = models["analog_knn"]
    out["p_analog_knn"] = knn.predict_proba(scaler.transform(df[KNN_FEATURES]))[:, 1]
    return out


def accuracy_by_time(test, bins=(30, 60, 90, 120, 180, 240, 300, 420, 600)):
    """Brier score of each model vs the market mid, and directional accuracy, by seconds to close (TEST)."""
    t = test.assign(tb=pd.cut(test.sec, list(bins)))
    rows = []
    for tb, g in t.groupby("tb", observed=True):
        r = {"sec_bin": str(tb), "n": len(g), "brier_market": np.mean((g.mid - g.y) ** 2), "acc_market": np.mean((g.mid > .5) == g.y)}
        for c in ("p_logit", "p_gbm", "p_analog_knn"):
            r[f"brier_{c[2:]}"] = np.mean((g[c] - g.y) ** 2)
            r[f"acc_{c[2:]}"] = np.mean((g[c] > .5) == g.y)
        rows.append(r)
    return pd.DataFrame(rows)


def entry_policy(df, pcol, margin, lo, hi, slip=0.01, delay=0):
    """First snapshot per market inside [lo, hi] s where model prob exceeds ask+slip+fee by `margin`; buy that side.
    delay=1: the order fills at the NEXT snapshot's ask (~15 s later); skipped if that snapshot is missing/too close to close."""
    c = df[(df.sec >= lo) & (df.sec <= hi)].sort_values(["ticker", "sec"], ascending=[True, False])
    ay, an = np.minimum(c.ask_yes + slip, .99), np.minimum(c.ask_no + slip, .99)
    fy, fn = M.FEE_RATE * ay * (1 - ay), M.FEE_RATE * an * (1 - an)
    ey, en = c[pcol] - ay - fy, (1 - c[pcol]) - an - fn
    c = c.assign(buy_yes=ey >= en, edge=np.maximum(ey, en))
    c = c[c.edge > margin].groupby("ticker", sort=False).head(1)
    if delay:
        c = c[c.next_ask_yes.notna() & c.next_ask_no.notna() & (c.next_sec >= 20)]
        raw = np.where(c.buy_yes, c.next_ask_yes, c.next_ask_no)
    else:
        raw = np.where(c.buy_yes, c.ask_yes, c.ask_no)
    price = np.minimum(raw + slip, .99)
    win = (c.y == 1) == c.buy_yes
    pnl = win.astype(float) - price - M.FEE_RATE * price * (1 - price)
    return pd.DataFrame({"ticker": c.ticker.values, "sec": c.sec.values, "price": price, "win": win.values, "pnl": pnl.values})


def policy_grid(dev, test, pcols=("p_logit", "p_gbm", "p_analog_knn"), margins=(0.02, 0.05, 0.08, 0.12),
                windows=((30, 120), (30, 180), (60, 300), (120, 600), (30, 600))):
    """EV per contract (after fee + 1c slippage) for each model/margin/entry-window; dev, test and test with 15 s fill delay."""
    rows = []
    for p in pcols:
        for m in margins:
            for lo, hi in windows:
                a, b, bd = (entry_policy(dev, p, m, lo, hi), entry_policy(test, p, m, lo, hi),
                            entry_policy(test, p, m, lo, hi, delay=1))
                rows.append({"model": p[2:], "margin": m, "window": f"{lo}-{hi}s",
                             "n_dev": len(a), "ev_dev": a.pnl.mean() if len(a) else np.nan,
                             "n_test": len(b), "wr_test": b.win.mean() if len(b) else np.nan,
                             "ev_test": b.pnl.mean() if len(b) else np.nan,
                             "ev_test_se": b.pnl.std() / np.sqrt(len(b)) if len(b) > 1 else np.nan,
                             "n_test_delay": len(bd), "ev_test_delay15s": bd.pnl.mean() if len(bd) else np.nan})
    return pd.DataFrame(rows)


def export_logit(logit):
    """Save the logistic model so another process can score it: p = 1/(1+exp(-(intercept + sum(coef_i * x_i))))."""
    import json
    spec = {"features": FEATURES, "intercept": float(logit.intercept_[0]), "coef": [float(c) for c in logit.coef_[0]],
            "feature_definitions": {"pct": "100*ln(reference_price/floor_strike)",
                                    "sigma": "std of pct change per snapshot over last 20 snapshots, floor 1e-4",
                                    "z": "pct/(sigma*sqrt(sec/15))", "sec": "seconds to close",
                                    **{f"d{k}": f"(pct_now-pct_{k}_snapshots_ago)/(sigma*sqrt({k}))" for k in LAGS}},
            "trained_on": "markets first seen before 2026-10-27 (dev)", "note": "offline; shadow-log before trading"}
    (OUT_SIM / "pattern_logit_model.json").write_text(json.dumps(spec, indent=2))


def export_analog(samples, k=150, conf=0.93):
    """Fit the analog (k-NN) model on ALL markets and save what a bot needs: training rows + scaler + parameters."""
    import json
    scaler = StandardScaler().fit(samples[KNN_FEATURES])
    samples[KNN_FEATURES + ["y"]].round(6).to_csv(OUT_SIM / "analog_model_train.csv", index=False)
    spec = {"model": "k-NN analog, euclidean on standardized features, weights=1/distance (distance 0 -> only those rows)",
            "k": k, "buy_if_probability_at_least": conf, "decision_time_seconds_to_close": 240,
            "features": KNN_FEATURES, "scaler_mean": [float(v) for v in scaler.mean_], "scaler_scale": [float(v) for v in scaler.scale_],
            "training_rows": "analog_model_train.csv (same column order, y = 1 if market settled YES)",
            "feature_definitions": {"pct": "100*ln(reference_price/floor_strike)",
                                    "sigma": "std of pct change per snapshot (15 s) over the last 20 snapshots, floor 1e-4",
                                    "z": "pct/(sigma*sqrt(sec/15))", "sec": "seconds to close",
                                    **{f"d{n}": f"(pct_now-pct_{n}_snapshots_ago)/(sigma*sqrt({n}))" for n in LAGS}},
            "decision": "p_yes>=0.5 -> buy YES with prob p_yes, else buy NO with prob 1-p_yes; enter if prob >= buy_if_probability_at_least",
            "trained_on_markets": int(samples.ticker.nunique())}
    (OUT_SIM / "analog_model.json").write_text(json.dumps(spec, indent=2))
    return spec


def score_analog(spec, train, x):
    """Reference scorer (numpy only, no sklearn): P(yes) for feature dict `x`. Matches KNeighborsClassifier(weights='distance')."""
    feats = spec["features"]
    mu, sd = np.array(spec["scaler_mean"]), np.array(spec["scaler_scale"])
    Z = (train[feats].values - mu) / sd
    q = (np.array([x[f] for f in feats]) - mu) / sd
    dist = np.sqrt(((Z - q) ** 2).sum(axis=1))
    idx = np.argpartition(dist, spec["k"])[:spec["k"]]
    d, y = dist[idx], train["y"].values[idx]
    if (d == 0).any():
        return float(y[d == 0].mean())
    w = 1 / d
    return float((w * y).sum() / w.sum())


def decision_snapshots(df, sec=240, tol=15):
    """One decision per market: the snapshot closest to `sec` seconds before close (within +-tol)."""
    x = df[(df.sec >= sec - tol) & (df.sec <= sec + tol)].copy()
    x["dist"] = (x.sec - sec).abs()
    return x.sort_values("dist").groupby("ticker").head(1)


def gate_trade(x, pcol, conf, slip=0.01, delay=0):
    """Buy the model's favoured side if its probability >= conf. delay=1 fills at the next snapshot's ask."""
    py = x[pcol].values
    yes = py >= 0.5
    prob = np.where(yes, py, 1 - py)
    ask = np.where(yes, x.next_ask_yes if delay else x.ask_yes, x.next_ask_no if delay else x.ask_no)
    price = np.minimum(ask + slip, .99)
    ok = (prob >= conf) & (ask + slip <= .99) & ~np.isnan(price)
    win = (x.y.values == 1) == yes
    pnl = win.astype(float) - price - M.FEE_RATE * price * (1 - price)
    n = int(ok.sum())
    return {"n": n, "wr": win[ok].mean() if n else np.nan, "avg_price": price[ok].mean() if n else np.nan,
            "ev": pnl[ok].mean() if n else np.nan, "se": pnl[ok].std() / np.sqrt(n) if n > 1 else np.nan}


def four_minute_gate(dev_p, test_p, sec=240, confs=(0.80, 0.85, 0.90, 0.93, 0.95)):
    """Decide once, ~`sec` s before close: if the model recognises the gap/path as a high-confidence one, buy that side.
    Dev EV is shown only for logit/gbm (the k-NN fits its own training rows, so its dev numbers are in-sample)."""
    d, t = decision_snapshots(dev_p, sec), decision_snapshots(test_p, sec)
    rows = []
    for pcol in ("p_logit", "p_gbm", "p_analog_knn"):
        for conf in confs:
            for fill, kw in (("immediate", {}), ("delay15s", {"delay": 1})):
                a, b = gate_trade(d, pcol, conf, **kw), gate_trade(t, pcol, conf, **kw)
                rows.append({"model": pcol[2:], "conf": conf, "fill": fill,
                             "n_dev": a["n"] if pcol != "p_analog_knn" else np.nan,
                             "ev_dev": a["ev"] if pcol != "p_analog_knn" else np.nan,
                             "n_test": b["n"], "wr_test": b["wr"], "avg_price_test": b["avg_price"],
                             "ev_test": b["ev"], "ev_test_se": b["se"]})
    return pd.DataFrame(rows)


def run(save=True):
    s = build_samples()
    dev, test = s[s.period == "dev"], s[s.period == "test"]
    models = fit_models(dev)
    if save:
        export_logit(models["logit"])
        export_analog(s)
    dev_p, test_p = predict(models, dev), predict(models, test)
    acc = accuracy_by_time(test_p)
    grid = policy_grid(dev_p, test_p)
    gate = four_minute_gate(dev_p, test_p)
    if save:
        acc.to_csv(OUT_SIM / "pattern_model_by_time.csv", index=False)
        grid.to_csv(OUT_SIM / "pattern_model_policy_grid.csv", index=False)
        gate.to_csv(OUT_SIM / "pattern_model_4min_gate.csv", index=False)
    return {"samples": pd.Series({"rows_dev": len(dev), "rows_test": len(test), "markets_dev": dev.ticker.nunique(),
                                  "markets_test": test.ticker.nunique()}),
            "accuracy_by_time": acc, "4min_gate (decide once at ~240 s)": gate, "policy_grid": grid}
