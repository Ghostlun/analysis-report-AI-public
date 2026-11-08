"""Load, validate and resample the KXBTC15M market snapshot file.

Terminology (never conflate):
  * ``reference_price_usd``  - BTC reference index level (CF Benchmarks BRTI), USD per BTC.
  * ``yes_*`` / ``no_*`` / ``last_price_usd`` - Kalshi contract prices (USD per contract, 0-1). Not BTC prices.
  * ``volume_contracts``     - Kalshi contract volume. Not BTC spot volume.

Only an allowlisted set of columns is ever read from disk (see ``LOAD_COLUMNS``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKET_CSV = ROOT / "data" / "raw" / "KXBTC15M_all.csv"

REQUIRED_COLUMNS = (
    "ticker",
    "collected_at_utc",
    "reference_timestamp",
    "reference_price_usd",
    "floor_strike",
    "close_time",
)
OPTIONAL_COLUMNS = (
    "yes_bid_usd", "yes_ask_usd", "no_bid_usd", "no_ask_usd", "last_price_usd",
    "volume_contracts", "official_settlement_result", "settlement_status", "settlement_timestamp",
)
LOAD_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
TIMESTAMP_COLUMNS = ("collected_at_utc", "reference_timestamp", "close_time", "settlement_timestamp")
NUMERIC_COLUMNS = (
    "reference_price_usd", "floor_strike", "yes_bid_usd", "yes_ask_usd", "no_bid_usd", "no_ask_usd",
    "last_price_usd", "volume_contracts",
)
CONTRACT_PRICE_COLUMNS = ("yes_bid_usd", "yes_ask_usd", "no_bid_usd", "no_ask_usd", "last_price_usd")

INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h"}
DEFAULT_MAX_GAP_SECONDS = 300.0
FORBIDDEN_FILENAME_PARTS = ("live_orders",)


class DataValidationError(ValueError):
    """Raised when the input file is unusable (missing columns, forbidden file, nothing parseable)."""


@dataclass
class LoadReport:
    """Source metadata and data-quality counts. Contains no market rows."""
    source_file: str
    sha256: str
    file_size_bytes: int
    rows_read: int
    columns_loaded: list[str]
    invalid_timestamps: dict[str, int] = field(default_factory=dict)
    invalid_numeric: dict[str, int] = field(default_factory=dict)
    out_of_range_contract_prices: int = 0
    non_positive_reference_prices: int = 0
    null_reference_rows: int = 0
    rows_with_valid_reference: int = 0
    collected_at_start: str | None = None
    collected_at_end: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_not_private(path: Path) -> None:
    parts = {p.lower() for p in path.parts}
    if any(s in path.name.lower() for s in FORBIDDEN_FILENAME_PARTS) or "actual" in parts:
        raise DataValidationError("refusing to load live-order / actual-trade data in the public research pipeline")


def validate_columns(columns) -> None:
    have = set(columns)
    missing = [c for c in REQUIRED_COLUMNS if c not in have]
    if missing:
        raise DataValidationError(f"missing required columns: {missing}")


def parse_utc(series: pd.Series) -> pd.Series:
    """Parse mixed ISO-8601 strings to tz-aware UTC; unparseable values become NaT."""
    return pd.to_datetime(series, utc=True, format="mixed", errors="coerce")


def clean_market_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Validate, type and sort a raw snapshot frame. Pure function (no file access); returns (frame, counts)."""
    validate_columns(raw.columns)
    df = raw.copy()
    counts: dict = {"invalid_timestamps": {}, "invalid_numeric": {}}

    for c in TIMESTAMP_COLUMNS:
        if c in df.columns:
            parsed = parse_utc(df[c])
            counts["invalid_timestamps"][c] = int((parsed.isna() & df[c].notna()).sum())
            df[c] = parsed

    for c in NUMERIC_COLUMNS:
        if c in df.columns:
            num = pd.to_numeric(df[c], errors="coerce").astype("float64")
            num = num.where(np.isfinite(num))
            counts["invalid_numeric"][c] = int((num.isna() & df[c].notna()).sum())
            df[c] = num

    # contract prices must lie in [0, 1]; anything else is invalid, not clipped
    bad = 0
    for c in CONTRACT_PRICE_COLUMNS:
        if c in df.columns:
            m = df[c].notna() & ((df[c] < 0) | (df[c] > 1))
            bad += int(m.sum())
            df.loc[m, c] = np.nan
    counts["out_of_range_contract_prices"] = bad

    nonpos = df["reference_price_usd"].notna() & (df["reference_price_usd"] <= 0)
    counts["non_positive_reference_prices"] = int(nonpos.sum())
    df.loc[nonpos, "reference_price_usd"] = np.nan

    # a reference price without a valid reference timestamp cannot be placed in time: drop the price, keep the row
    orphan = df["reference_price_usd"].notna() & df["reference_timestamp"].isna()
    df.loc[orphan, "reference_price_usd"] = np.nan

    n_before = len(df)
    df = df[df["collected_at_utc"].notna()]
    counts["dropped_rows_no_collection_time"] = n_before - len(df)
    if n_before and df.empty:
        raise DataValidationError("no row has a parseable collected_at_utc")

    df = df.sort_values(["collected_at_utc", "ticker"], kind="mergesort").reset_index(drop=True)
    return df, counts


def load_market_snapshots(path: str | Path | None = None) -> tuple[pd.DataFrame, LoadReport]:
    """Load the KXBTC15M file (allowlisted columns only), validate and sort chronologically by ``collected_at_utc``."""
    p = Path(path) if path is not None else DEFAULT_MARKET_CSV
    _check_not_private(p)
    if not p.exists():
        raise DataValidationError(f"market file not found: {p.name}")
    header = pd.read_csv(p, nrows=0).columns
    validate_columns(header)
    usecols = [c for c in LOAD_COLUMNS if c in header]
    raw = pd.read_csv(p, usecols=usecols, low_memory=False)
    df, counts = clean_market_frame(raw)
    valid_ref = df["reference_price_usd"].notna()
    report = LoadReport(
        source_file=p.name,
        sha256=_sha256(p),
        file_size_bytes=p.stat().st_size,
        rows_read=len(raw),
        columns_loaded=usecols,
        invalid_timestamps=counts["invalid_timestamps"],
        invalid_numeric=counts["invalid_numeric"],
        out_of_range_contract_prices=counts["out_of_range_contract_prices"],
        non_positive_reference_prices=counts["non_positive_reference_prices"],
        null_reference_rows=int((~valid_ref).sum()),
        rows_with_valid_reference=int(valid_ref.sum()),
        collected_at_start=df["collected_at_utc"].min().isoformat() if len(df) else None,
        collected_at_end=df["collected_at_utc"].max().isoformat() if len(df) else None,
    )
    df.attrs["source_file"] = report.source_file
    df.attrs["sha256"] = report.sha256
    return df, report


@dataclass
class ReferenceSeries:
    """Unique BTC reference observations, one per ``reference_timestamp``, ascending."""
    data: pd.DataFrame        # reference_timestamp, reference_price_usd, first_collected_at_utc, n_source_rows
    conflicts: pd.DataFrame   # reference_timestamp, n_distinct_prices, min_price, max_price, chosen_price
    duplicate_rows_removed: int
    resolution_rule: str = "earliest collected_at_utc wins; ties broken by lowest price"


_CONFLICT_COLS = ["reference_timestamp", "n_distinct_prices", "min_price", "max_price", "chosen_price"]


def build_reference_series(df: pd.DataFrame) -> ReferenceSeries:
    """Deduplicate BTC reference observations by ``reference_timestamp`` (never ``collected_at_utc``).

    Rows with a null price or timestamp are excluded (never filled). When one timestamp carries different prices the
    earliest-collected value (ties: lowest price) is kept deterministically and the conflict is reported.
    """
    validate_columns(df.columns)
    cols = ["reference_timestamp", "reference_price_usd", "collected_at_utc"]
    r = df.loc[df["reference_price_usd"].notna() & df["reference_timestamp"].notna(), cols]
    if r.empty:
        data = pd.DataFrame({
            "reference_timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
            "reference_price_usd": pd.Series(dtype="float64"),
            "first_collected_at_utc": pd.Series(dtype="datetime64[ns, UTC]"),
            "n_source_rows": pd.Series(dtype="int64"),
        })
        return ReferenceSeries(data, pd.DataFrame(columns=_CONFLICT_COLS), 0)

    r = r.sort_values(["reference_timestamp", "collected_at_utc", "reference_price_usd"], kind="mergesort")
    g = r.groupby("reference_timestamp", sort=True)
    first = g.head(1).set_index("reference_timestamp")
    stats = g["reference_price_usd"].agg(["nunique", "min", "max", "size"])
    data = pd.DataFrame({
        "reference_timestamp": first.index,
        "reference_price_usd": first["reference_price_usd"].to_numpy(),
        "first_collected_at_utc": first["collected_at_utc"].to_numpy(),
        "n_source_rows": stats["size"].reindex(first.index).to_numpy(),
    }).reset_index(drop=True)

    cf = stats[stats["nunique"] > 1]
    if len(cf):
        conflicts = pd.DataFrame({
            "reference_timestamp": cf.index,
            "n_distinct_prices": cf["nunique"].to_numpy(),
            "min_price": cf["min"].to_numpy(),
            "max_price": cf["max"].to_numpy(),
            "chosen_price": first["reference_price_usd"].reindex(cf.index).to_numpy(),
        }).reset_index(drop=True)
    else:
        conflicts = pd.DataFrame(columns=_CONFLICT_COLS)
    return ReferenceSeries(data, conflicts, int(len(r) - len(data)))


def detect_gaps(times: pd.Series, max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS) -> pd.DataFrame:
    """Gaps between consecutive observations that exceed ``max_gap_seconds``. Input is sorted internally."""
    t = pd.Series(pd.to_datetime(times, utc=True)).dropna().sort_values().reset_index(drop=True)
    d = t.diff().dt.total_seconds()
    idx = d.index[d > max_gap_seconds]
    return pd.DataFrame({
        "gap_start": pd.to_datetime(t.shift(1)[idx].to_numpy(), utc=True),
        "gap_end": pd.to_datetime(t[idx].to_numpy(), utc=True),
        "gap_seconds": d[idx].to_numpy(dtype="float64"),
    }).reset_index(drop=True)


def resample_reference(
    series: ReferenceSeries | pd.DataFrame,
    interval: str,
    max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
) -> pd.DataFrame:
    """Resample the de-duplicated BTC reference series to fixed bars (close-only index levels, not OHLC).

    Bars are right-closed and labelled by their end: bar ``t`` covers ``(t - interval, t]`` and uses only observations
    with ``reference_timestamp <= t`` (no look-ahead). ``close`` is the last observation in the bar. Empty bars are
    kept with ``close = NaN`` (never forward-filled).

    Columns:
      close, n_obs, first_obs_time, last_obs_time
      partial       - first bar starting more than ``max_gap_seconds`` after its own start, or last bar whose last
                      observation is more than ``max_gap_seconds`` before its end
      gap_affected  - a collection gap longer than ``max_gap_seconds`` overlaps the bar
      segment       - integer id of a run of bars with continuous data; increments at the first bar after a missing
                      bar or collection gap (missing bars keep the previous id and have close = NaN). Indicators
                      must not be computed across segments.
    """
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {sorted(INTERVALS)}")
    data = series.data if isinstance(series, ReferenceSeries) else series
    cols = ["close", "n_obs", "first_obs_time", "last_obs_time", "partial", "gap_affected", "segment"]
    if data.empty:
        out = pd.DataFrame(columns=cols)
        out.index = pd.DatetimeIndex([], tz="UTC", name="bar_end")
        return out

    rule = INTERVALS[interval]
    freq = pd.Timedelta(rule)
    d = data.sort_values("reference_timestamp", kind="mergesort")
    ts = d["reference_timestamp"]
    bar_end = ts.dt.ceil(rule)  # an observation exactly on a boundary belongs to the bar ending there
    g = d.assign(bar_end=bar_end.to_numpy()).groupby("bar_end", sort=True)
    agg = pd.DataFrame({
        "close": g["reference_price_usd"].last(),
        "n_obs": g["reference_price_usd"].size(),
        "first_obs_time": g["reference_timestamp"].first(),
        "last_obs_time": g["reference_timestamp"].last(),
    })
    full = pd.date_range(agg.index.min(), agg.index.max(), freq=rule, name="bar_end")
    if full.tz is None:
        full = full.tz_localize("UTC")
    bars = agg.reindex(full)
    bars["n_obs"] = bars["n_obs"].fillna(0).astype(int)

    first_ts, last_ts = ts.iloc[0], ts.iloc[-1]
    tol = pd.Timedelta(seconds=max_gap_seconds)
    partial = np.zeros(len(bars), dtype=bool)
    if first_ts - (bars.index[0] - freq) > tol:
        partial[0] = True
    if bars.index[-1] - last_ts > tol:
        partial[-1] = True
    bars["partial"] = partial

    gaps = detect_gaps(ts, max_gap_seconds)
    affected = np.zeros(len(bars), dtype=bool)
    for gs, ge in zip(gaps["gap_start"], gaps["gap_end"]):
        affected |= np.asarray((bars.index - freq < ge) & (bars.index > gs))
    bars["gap_affected"] = affected

    # segment breaks: a missing bar (or the bar after one), or a gap between the previous bar's last obs and this first obs
    prev_last = bars["last_obs_time"].shift(1)
    big = ((bars["first_obs_time"] - prev_last).dt.total_seconds() > max_gap_seconds).fillna(False)
    brk = bars["close"].notna() & (bars["close"].shift(1).isna() | big)
    bars["segment"] = brk.cumsum().astype(int)
    return bars[cols]
