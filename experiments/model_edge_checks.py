import numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from model_edge import *
df = pd.read_csv(__import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "raw" / "KXBTC15M_all.csv", usecols=["collected_at_utc", "source_timestamp", "reference_timestamp"])
a = pd.to_datetime(df.collected_at_utc, utc=True); b = pd.to_datetime(df.source_timestamp, utc=True, errors="coerce")
lag = (a - b).dt.total_seconds().dropna()
print("\ncollected_at - source_timestamp (s):", lag.describe(percentiles=[.5, .9, .99]).round(2).to_dict())
fn = edge_rule(0.04)
print("\nmargin 0.04 normal, all 586 markets")
for scen in ("S0_quoted", "S1_project", "S2_delay15s", "S3_delay_worse", "S4_thin_book"):
    print(f"{scen:15s} {line(ms, fn, scen)}")
tr, _ = run_strategy(ms, fn, "S1_project")
d = pd.DataFrame([x.__dict__ for x in tr])
print("entry ask quantiles:", d.ask_q.quantile([.1, .5, .9]).round(2).to_dict(), " entry sec quantiles:", d.entry_sec.quantile([.1, .5, .9]).round(0).to_dict(), " avg contracts:", round(d.n.mean(), 1))
print("by day net:", d.groupby("day").pnl.sum().round(1).to_dict())
