import pandas as pd, numpy as np
df = pd.read_csv(__import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "raw" / "KXBTC15M_all.csv")
df["close_time"] = pd.to_datetime(df.close_time, utc=True)
mk = df.groupby("ticker").agg(close=("close_time", "first"), strike=("floor_strike", "first"), final=("official_final_btc_price_usd", "first"),
                              res=("official_settlement_result", "first")).sort_values("close").dropna(subset=["res", "final", "strike"])
mk["move"] = mk.final - mk.strike  # signed move during this market
mk["gap"] = mk.close.diff().dt.total_seconds()
mk["prev_move"] = mk.move.shift(1); mk["yes"] = (mk.res == "yes").astype(int)
c = mk[mk.gap == 900].copy()
print("n", len(c), "corr(prev_move, this_move) = %.3f" % c.prev_move.corr(c.move))
c["b"] = pd.cut(c.prev_move, [-1e9, -100, -30, 0, 30, 100, 1e9], labels=["<-100", "-100~-30", "-30~0", "0~30", "30~100", ">100"])
print(c.groupby("b", observed=True).agg(n=("yes", "size"), next_yes=("yes", "mean"), next_move_mean=("move", "mean")).round(3).to_string())
print("sign agreement of consecutive moves: %.3f" % (np.sign(c.prev_move) == np.sign(c.move)).mean())
