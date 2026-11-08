"""Project-relative paths. Set KALSHI_DATA_DIR to read the input CSVs from another folder."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("KALSHI_DATA_DIR", ROOT / "data" / "raw"))
OUT_ACTUAL = ROOT / "outputs" / "actual"        # derived from real live orders
OUT_SIM = ROOT / "outputs" / "simulated"        # derived from replays/backtests
REPORTS = ROOT / "reports"

MARKET_CSV = RAW / "KXBTC15M_all.csv"
ORDERS_CSV = RAW / "live_orders_all.csv"

for _d in (OUT_ACTUAL, OUT_SIM):
    _d.mkdir(parents=True, exist_ok=True)
