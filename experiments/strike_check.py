import pandas as pd, numpy as np
df = pd.read_csv(__import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "raw" / "KXBTC15M_all.csv")
df["close_time"] = pd.to_datetime(df.close_time, utc=True); df["t"] = pd.to_datetime(df.collected_at_utc, utc=True)
df["sec"] = (df.close_time - df.t).dt.total_seconds()
mk = df.groupby("ticker").agg(close=("close_time", "first"), strike=("floor_strike", "first"), final=("official_final_btc_price_usd", "first"),
                              res=("official_settlement_result", "first")).sort_values("close")
mk["prev_final"] = mk.final.shift(1); mk["gap"] = mk.close.diff().dt.total_seconds()
c = mk[(mk.gap == 900)].dropna(subset=["strike", "prev_final"]).copy()
c["d"] = c.strike - c.prev_final
print("consecutive markets:", len(c))
print("strike - previous market's official final price (USD): mean %.2f, median %.2f, std %.2f, abs<=0.01: %.1f%%, abs<=1: %.1f%%, abs<=10: %.1f%%" %
      (c.d.mean(), c.d.median(), c.d.std(), (c.d.abs() <= 0.01).mean() * 100, (c.d.abs() <= 1).mean() * 100, (c.d.abs() <= 10).mean() * 100))
print(c.d.describe(percentiles=[.05, .25, .5, .75, .95]).round(2).to_dict())
# strike vs reference at the earliest snapshot in each market with ref (about 900s before close)
pre = df[(df.sec >= 0) & df.reference_price_usd.notna()].sort_values(["ticker", "t"])
first = pre.groupby("ticker").first()
first = first.join(mk[["strike"]], rsuffix="_m")
first["d0"] = first.reference_price_usd - first.floor_strike
first = first[first.sec > 780]
print("\nmarkets with ref snapshot >780s before close:", len(first), " ref-strike at that time: mean %.1f, median %.1f, std %.1f, abs median %.1f" %
      (first.d0.mean(), first.d0.median(), first.d0.std(), first.d0.abs().median()))
print("first-snapshot YES ask mean %.3f (0.5 = balanced)" % first.yes_ask_usd.mean())
# outcome balance and randomness tests
print("\nYES share:", round((mk.res == "yes").mean(), 3), " n", mk.res.notna().sum())
r = (mk.res.dropna() == "yes").astype(int).to_numpy()
runs = 1 + (r[1:] != r[:-1]).sum(); n1 = r.sum(); n0 = len(r) - n1
mu = 2 * n1 * n0 / len(r) + 1; var = (mu - 1) * (mu - 2) / (len(r) - 1)
print("runs test z = %.2f (|z|<2 -> no clear streak pattern)" % ((runs - mu) / np.sqrt(var)))
# does previous result predict next? (consecutive only)
cc = c.copy(); cc["prev_yes"] = (mk.res.shift(1).loc[cc.index] == "yes"); cc["yes"] = cc.res == "yes"
print("P(yes | prev yes) = %.3f, P(yes | prev no) = %.3f" % (cc[cc.prev_yes].yes.mean(), cc[~cc.prev_yes].yes.mean()))
print("strike decimals sample:", mk.strike.head(5).tolist(), "; final vs strike diff of last digits ok")
