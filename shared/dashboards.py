"""Builders for the four public research dashboard documents (plain dicts, validated by ``dashboard_schemas``).

Inputs are limited to the approved sources: the KXBTC15M snapshot file (via ``shared.data_loader``) and the aggregate
simulated-result CSVs in ``outputs/simulated/``. Nothing here reads live orders or ``outputs/actual``. Builders are
pure functions of their inputs (apart from the ``generated_at`` argument), so analytical content is deterministic.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import data_loader as dl
from . import indicators as ind
from .dashboard_schemas import PUBLICATION_STATUS, SCHEMA_VERSION
from .metrics import KALSHI_FEE_RATE, wilson_interval

SPLIT_UTC = "2026-10-27T00:00:00Z"  # dev/test split used by the existing research code (src/momentum.py::SPLIT)
N_CONTRACTS_MOMENTUM = 5            # contracts per simulated trade in the momentum grid (src/momentum.py::N_CONTRACTS)
SLIPPAGE_USD = 0.01
PREDICTION_FILE = "pattern_model_by_time.csv"
STRATEGY_FILES = {
    "pattern_model_policy_grid.csv": ("n_dev", "ev_dev", "n_test", "wr_test", "ev_test", "ev_test_se", "n_test_delay",
                                      "ev_test_delay15s", "model"),
    "pattern_model_4min_gate.csv": ("model", "fill", "n_dev", "ev_dev", "n_test", "wr_test", "ev_test", "ev_test_se"),
    "gap_rule_results.csv": ("fill", "period", "n", "wr", "ev_per_contract", "se"),
    "momentum_v2_dev_grid.csv": ("n", "wins", "net", "maxdd"),
}
MODEL_IDS = {"logit": "logistic", "gbm": "gradient_boosting", "analog_knn": "knn_analog"}
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
GAP_SECONDS = dl.DEFAULT_MAX_GAP_SECONDS
TIME_BINS = [(0, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 300), (300, 600), (600, 900)]
DISCLAIMERS = [
    "Historical research snapshot of simulated/analytical results; not live data, not investment advice.",
    "Public aggregate only; raw market data and account-level records are excluded.",
]


class MissingInputError(RuntimeError):
    """An approved source file is missing or lacks required columns."""


# ----------------------------------------------------------------------------- helpers
def ts(t) -> str | None:
    if t is None or pd.isna(t):
        return None
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def num(x, nd: int = 6):
    """Finite float rounded, else None (never NaN/Inf)."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_simulated_csv(path: Path, required) -> pd.DataFrame:
    if not path.exists():
        raise MissingInputError(f"missing approved input: {path.name}")
    df = pd.read_csv(path)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise MissingInputError(f"{path.name} lacks required columns: {missing}")
    return df


def _meta(dashboard, generated_at, as_of, start, end, counts, files):
    return {
        "schema_version": SCHEMA_VERSION,
        "dashboard": dashboard,
        "generated_at": generated_at,
        "data_status": {"kind": "historical_research_snapshot", "is_live": False, "as_of": as_of,
                        "description": "Static analysis of previously collected data. Values are not live prices."},
        "publication_status": {"status": PUBLICATION_STATUS, "approved_for_public_release": True,
                               "notes": "Allowlisted portfolio aggregate; raw source data, private orders, and "
                                        "credentials are excluded."},
        "source_window": {"start": start, "end": end},
        "sample_counts": counts,
        "source_files": [{"name": n, "role": r, "sha256": s} for n, r, s in files],
        "disclaimers": list(DISCLAIMERS),
    }


class Sources:
    """Loaded approved sources plus their hashes (hashes are of the files as read)."""

    def __init__(self, market_csv: Path, simulated_dir: Path):
        self.market_csv = Path(market_csv)
        self.simulated_dir = Path(simulated_dir)
        self.df, self.report = dl.load_market_snapshots(self.market_csv)
        self.ref = dl.build_reference_series(self.df)
        self.files = {self.market_csv.name: ("KXBTC15M market snapshots", self.report.sha256)}

    def sim(self, name, required):
        p = self.simulated_dir / name
        df = read_simulated_csv(p, required)
        self.files[name] = ("aggregate simulated results", _sha(p))
        return df

    def file_list(self, names):
        return [(n, self.files[n][0], self.files[n][1]) for n in names]


# ----------------------------------------------------------------------------- market overview
def _bar_series(bars: pd.DataFrame) -> dict:
    return {
        "time": [ts(t) for t in bars.index],
        "close": [num(v, 2) for v in bars["close"]],
        "n_obs": [int(v) for v in bars["n_obs"]],
        "partial": [bool(v) for v in bars["partial"]],
        "gap_affected": [bool(v) for v in bars["gap_affected"]],
    }


def _settlement(df: pd.DataFrame) -> dict:
    g = df.dropna(subset=["official_settlement_result"]).groupby("ticker")["official_settlement_result"]
    nun = g.nunique()
    conflicting = int((nun > 1).sum())
    first = g.first()
    markets = int(df["ticker"].nunique())
    first = first[nun <= 1].str.lower()
    yes, no = int((first == "yes").sum()), int((first == "no").sum())
    settled = yes + no
    ci = wilson_interval(yes, settled) if settled else (None, None)
    close = df.groupby("ticker")["close_time"].first().reindex(first.index)
    by = pd.DataFrame({"d": close.dt.strftime("%Y-%m-%d").to_numpy(), "r": first.to_numpy()})
    rows = []
    for d, grp in by.groupby("d", sort=True):
        rows.append({"date": d, "settled_markets": int(len(grp)), "yes": int((grp.r == "yes").sum()),
                     "no": int((grp.r == "no").sum())})
    return {
        "status": "available" if settled else "unavailable", "markets": markets, "settled_yes": yes, "settled_no": no,
        "unsettled_or_unknown": markets - settled, "markets_with_conflicting_outcome": conflicting,
        "yes_share_of_settled": num(yes / settled) if settled else None,
        "yes_share_ci95_lo": num(ci[0]) if settled else None, "yes_share_ci95_hi": num(ci[1]) if settled else None,
        "by_close_date": rows,
    }, settled


def _implied_probability(df: pd.DataFrame) -> dict:
    q = df.dropna(subset=["yes_bid_usd", "yes_ask_usd", "official_settlement_result"]).copy()
    q = q[q["yes_ask_usd"] >= q["yes_bid_usd"]]
    q["p"] = (q["yes_bid_usd"] + q["yes_ask_usd"]) / 2.0
    q["sec"] = (q["close_time"] - q["collected_at_utc"]).dt.total_seconds()
    inside = q[(q["sec"] > 0) & (q["sec"] <= 900)].copy()
    excluded = int(len(q) - len(inside))
    inside["y"] = (inside["official_settlement_result"].str.lower() == "yes").astype(float)
    bins = []
    for lo, hi in TIME_BINS:
        s = inside[(inside["sec"] > lo) & (inside["sec"] <= hi)]
        bins.append({
            "bin": f"({lo}, {hi}]", "seconds_lo": lo, "seconds_hi": hi, "n_snapshots": int(len(s)),
            "n_markets": int(s["ticker"].nunique()),
            "mean_implied_prob_yes": num(s["p"].mean()) if len(s) else None,
            "observed_yes_rate_snapshot_weighted": num(s["y"].mean()) if len(s) else None})
    dist = []
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        m = (inside["p"] >= lo) & ((inside["p"] < hi) if i < 9 else (inside["p"] <= hi))
        dist.append({"p_lo": lo, "p_hi": hi, "n_snapshots": int(m.sum())})
    ok = len(inside) > 0
    return {
        "status": "available" if ok else "unavailable",
        "reason": None if ok else "no two-sided yes quotes with settlement available",
        "unit": "probability (0-1) of the YES contract; Kalshi contract price in USD per $1 payout",
        "note": "Implied probability = midpoint of yes_bid and yes_ask. Snapshots within a market are strongly "
                "correlated; counts are snapshots, not independent observations.",
        "rows_used": int(len(inside)), "rows_excluded_outside_time_range": excluded,
        "by_time_to_close": bins, "distribution": dist}


def build_market_overview(src: Sources, generated_at: str) -> dict:
    df, rep, ref = src.df, src.report, src.ref
    data = ref.data
    n_ref = int(len(data))
    px = data["reference_price_usd"]
    gaps = dl.detect_gaps(data["reference_timestamp"], GAP_SECONDS)
    settlement, settled = _settlement(df)

    if n_ref:
        first_v, last_v = float(px.iloc[0]), float(px.iloc[-1])
        summary = {
            "status": "available", "index": "BTC reference index (reference_price_usd)",
            "unit": "USD per BTC", "n_observations": n_ref,
            "first_time": ts(data["reference_timestamp"].iloc[0]), "last_time": ts(data["reference_timestamp"].iloc[-1]),
            "first_value": num(first_v, 2), "last_value": num(last_v, 2), "min": num(px.min(), 2),
            "max": num(px.max(), 2), "mean": num(px.mean(), 2), "median": num(px.median(), 2),
            "change_pct_first_to_last": num(100 * (last_v / first_v - 1), 4)}
    else:
        summary = {"status": "unavailable", "index": "BTC reference index (reference_price_usd)", "unit": "USD per BTC",
                   "n_observations": 0, "first_time": None, "last_time": None, "first_value": None,
                   "last_value": None, "min": None, "max": None, "mean": None, "median": None,
                   "change_pct_first_to_last": None}

    daily = []
    if n_ref:
        d = data.assign(day=data["reference_timestamp"].dt.strftime("%Y-%m-%d"))
        for day, g in d.groupby("day", sort=True):
            p = g["reference_price_usd"]
            daily.append({"date": day, "n_observations": int(len(g)), "first": num(p.iloc[0], 2),
                          "last": num(p.iloc[-1], 2), "min": num(p.min(), 2), "max": num(p.max(), 2),
                          "mean": num(p.mean(), 2)})

    series = {"status": "available" if n_ref else "unavailable", "unit": "USD per BTC",
              "note": "Last reference observation in each right-closed bar (close-only index levels, not OHLC). "
                      "Empty bars have close null and are never forward-filled. Historical, not live.",
              "15m": _bar_series(dl.resample_reference(ref, "15m", GAP_SECONDS)),
              "1h": _bar_series(dl.resample_reference(ref, "1h", GAP_SECONDS))}

    two_sided = df["yes_bid_usd"].notna() & df["yes_ask_usd"].notna()
    ct = df["collected_at_utc"].drop_duplicates().sort_values()
    med_int = ct.diff().dt.total_seconds().median() if len(ct) > 1 else None
    counts = {
        "snapshot_rows": int(len(df)), "markets": int(df["ticker"].nunique()),
        "rows_with_btc_reference": rep.rows_with_valid_reference,
        "rows_with_two_sided_yes_quote": int(two_sided.sum()),
        "median_snapshot_interval_seconds": num(med_int, 2),
        "collected_start": rep.collected_at_start and ts(pd.Timestamp(rep.collected_at_start)),
        "collected_end": rep.collected_at_end and ts(pd.Timestamp(rep.collected_at_end)),
    }
    coverage = {
        "rows_with_reference": rep.rows_with_valid_reference, "rows_without_reference": rep.null_reference_rows,
        "share_rows_without_reference": num(rep.null_reference_rows / len(df), 4) if len(df) else None,
        "duplicate_reference_rows_removed": int(ref.duplicate_rows_removed),
        "conflicting_reference_timestamps": int(len(ref.conflicts)),
        "collection_gap_min_seconds": GAP_SECONDS, "collection_gap_count": int(len(gaps)),
        "longest_collection_gap_seconds": num(gaps["gap_seconds"].max(), 1) if len(gaps) else None,
        "total_gap_seconds": num(gaps["gap_seconds"].sum(), 1) if len(gaps) else None}

    return {
        "meta": _meta("market_overview", generated_at, counts["collected_end"], counts["collected_start"],
                      counts["collected_end"],
                      {"snapshot_rows": counts["snapshot_rows"], "markets": counts["markets"],
                       "reference_observations": n_ref, "settled_markets": settled},
                      src.file_list([src.market_csv.name])),
        "definitions": {
            "btc_reference_price": "BTC reference index level in USD per BTC (reference_price_usd). It is an index "
                                   "observation, not a Kalshi contract price and not an exchange trade price.",
            "contract_price": "Kalshi KXBTC15M YES/NO contract quote in USD per $1 payout (0-1). Not a BTC price.",
            "contract_volume": "Kalshi contract trading volume (volume_contracts). Not BTC spot trading volume.",
            "implied_probability": "Midpoint of YES bid and ask, interpreted as the market-implied probability of YES.",
            "time_to_close": "Seconds from collected_at_utc to the contract close_time (recomputed).",
        },
        "snapshot_counts": counts,
        "reference_price_summary": summary,
        "reference_coverage": coverage,
        "reference_price_series": series,
        "daily_reference_summary": daily,
        "settlement_outcomes": settlement,
        "implied_probability": _implied_probability(df),
        "contract_volume": {"status": "unavailable",
                            "reason": "volume_contracts units (cumulative vs per-snapshot, contracts vs dollars) are "
                                      "not verified, so no volume aggregate is published."},
        "btc_spot_volume": {"status": "unavailable",
                            "reason": "No BTC spot trading volume exists in the dataset; contract volume is not a substitute."},
    }


# ----------------------------------------------------------------------------- technical indicators
SMA_W, EMA_W, RSI_W, ROC_W, VOL_W = 20, 20, 14, 12, 24


def _interval_block(ref, interval: str) -> tuple[dict, int]:
    minutes = INTERVAL_MINUTES[interval]
    bars = dl.resample_reference(ref, interval, GAP_SECONDS)
    kw = dict(sma_windows=(SMA_W,), ema_windows=(EMA_W,), rsi_window=RSI_W, roc_windows=(ROC_W,), vol_windows=(VOL_W,))
    base = ind.compute_indicators(bars, **kw)
    ann = ind.compute_indicators(bars, annualize=True, bar_minutes=minutes, **kw)
    has = bars["close"].notna() if len(bars) else pd.Series(dtype=bool)
    excluded = has & (bars["partial"] | bars["gap_affected"]) if len(bars) else has
    cols = {"sma_20": base[f"sma_{SMA_W}"], "ema_20": base[f"ema_{EMA_W}"], "rsi_14": base[f"rsi_{RSI_W}"],
            "roc_12_pct": base[f"roc_{ROC_W}_pct"], "realized_vol_24_bar_pct": base[f"realized_vol_{VOL_W}_bar_pct"],
            "realized_vol_24_ann_pct": ann[f"realized_vol_{VOL_W}_ann_pct"]}
    nd = {"sma_20": 2, "ema_20": 2, "rsi_14": 3, "roc_12_pct": 4, "realized_vol_24_bar_pct": 5,
          "realized_vol_24_ann_pct": 3}
    series = {"time": [ts(t) for t in bars.index], "close": [num(v, 2) for v in bars["close"]]}
    for k, s in cols.items():
        series[k] = [num(v, nd[k]) for v in s]
    series["partial"] = [bool(v) for v in bars["partial"]]
    series["gap_affected"] = [bool(v) for v in bars["gap_affected"]]
    n = len(bars)
    block = {
        "status": "available" if int(has.sum()) else "unavailable", "bar_minutes": minutes,
        "bars_per_year": num(ind.bars_per_year(minutes), 3),
        "coverage": {
            "bars_total": n, "bars_with_data": int(has.sum()), "bars_missing": int((~has).sum()) if n else 0,
            "partial_bars": int(bars["partial"].sum()) if n else 0,
            "gap_affected_bars": int(bars["gap_affected"].sum()) if n else 0,
            "bars_excluded_from_indicators": int(excluded.sum()) if n else 0,
            "segments": int(bars.loc[has, "segment"].nunique()) if n else 0,
            "first_bar_end": ts(bars.index[0]) if n else None, "last_bar_end": ts(bars.index[-1]) if n else None,
            "missing_bar_share": num((~has).sum() / n, 4) if n else None},
        "valid_indicator_values": {k: int(s.notna().sum()) for k, s in cols.items()},
        "series": series,
    }
    return block, n


def build_technical_indicators(src: Sources, generated_at: str) -> dict:
    ref, rep = src.ref, src.report
    blocks, sizes = {}, {}
    for iv in ("1m", "5m", "15m", "1h"):
        blocks[iv], sizes[iv] = _interval_block(ref, iv)
    unavailable = lambda why: {"status": "unavailable", "reason": why}  # noqa: E731
    avail = {"status": "available", "reason": None}
    data = ref.data
    return {
        "meta": _meta("technical_indicators", generated_at, ts(data["reference_timestamp"].max()) if len(data) else None,
                      ts(data["reference_timestamp"].min()) if len(data) else None,
                      ts(data["reference_timestamp"].max()) if len(data) else None,
                      {"reference_observations": int(len(data)), "bars_1m": sizes["1m"], "bars_5m": sizes["5m"],
                       "bars_15m": sizes["15m"], "bars_1h": sizes["1h"]},
                      src.file_list([src.market_csv.name])),
        "input_series": {
            "name": "BTC reference index (reference_price_usd), de-duplicated by reference_timestamp", "unit": "USD per BTC",
            "type": "close-only index levels (last observation per bar); not OHLC",
            "note": "Kalshi contract prices are never used. Historical data; not live."},
        "indicator_status": {
            "sma": avail, "ema": avail, "rsi": avail, "momentum_roc": avail, "realized_volatility": avail,
            "atr": unavailable("True OHLC bars are not available; close-only reference levels cannot yield a true range."),
            "vwap": unavailable("BTC spot trading volume is not available."),
            "volume_indicators": unavailable("BTC spot trading volume is not available; contract volume is not a substitute."),
        },
        "parameters": {
            "sma_window_bars": SMA_W, "ema_window_bars": EMA_W, "rsi_window_bars": RSI_W, "roc_window_bars": ROC_W,
            "realized_vol_window_bars": VOL_W,
            "rsi_smoothing": "Wilder (seed = mean of first window gains/losses, then (prev*(n-1)+x)/n)",
            "rsi_flat_price_value": 50.0,
            "ema_seed": "alpha = 2/(window+1), seeded with the SMA of the first window closes",
            "collection_gap_min_seconds": GAP_SECONDS,
            "bar_convention": "Right-closed bars labelled by bar end; close = last observation with reference_timestamp <= bar end.",
            "volatility": {
                "estimator": "RMS of log returns (zero-mean realized volatility), not a demeaned sample standard deviation",
                "formula": "100 * sqrt(mean(r_i^2)) over the last window log returns, r_i = ln(C_i / C_(i-1)); needs window+1 closes",
                "unit_bar": "percent per bar", "unit_annualized": "percent per year",
                "annualization": "bar value * sqrt(525600 / bar_minutes), assuming 24/7 trading and independent returns; "
                                 "very noisy on this ~12-day sample",
                "mean_assumption": "mean log return assumed zero (not subtracted)"},
            "masking_rules": [
                "Missing bars have null close and are never forward-filled.",
                "Partial bars (first/last bar not fully covered by observations) are excluded from indicator inputs.",
                "Bars overlapping a collection gap longer than collection_gap_min_seconds are excluded from indicator inputs.",
                "Indicators restart their warm-up after any excluded or missing bar; values before warm-up completes are null.",
                "Indicator values use only data up to each bar's end (no look-ahead).",
            ]},
        "intervals": blocks,
    }


# ----------------------------------------------------------------------------- prediction analysis
def _parse_bin(label: str) -> tuple[int, int]:
    m = re.fullmatch(r"\(\s*(\d+)\s*,\s*(\d+)\s*\]", str(label))
    if not m:
        raise MissingInputError(f"unrecognised time bin label {label!r}")
    return int(m.group(1)), int(m.group(2))


def build_prediction_analysis(src: Sources, generated_at: str) -> dict:
    cols = ["sec_bin", "n"] + [f"{m}_{k}" for k in ("market", "logit", "gbm", "analog_knn")
                               for m in ("brier", "acc")]
    cols = ["sec_bin", "n", "brier_market", "acc_market", "brier_logit", "acc_logit", "brier_gbm", "acc_gbm",
            "brier_analog_knn", "acc_analog_knn"]
    d = src.sim(PREDICTION_FILE, cols).sort_values("sec_bin", key=lambda s: s.map(lambda x: _parse_bin(x)[0]))
    keys = {"market_baseline": "market", "logistic": "logit", "gradient_boosting": "gbm", "knn_analog": "analog_knn"}

    def skill(b, bm):
        return num(1 - b / bm, 6) if bm and math.isfinite(b) and math.isfinite(bm) and bm > 0 else None

    bins = []
    for _, r in d.iterrows():
        lo, hi = _parse_bin(r["sec_bin"])
        res = {"market_baseline": {"brier": num(r["brier_market"]), "accuracy": num(r["acc_market"])}}
        for mid, k in keys.items():
            if mid == "market_baseline":
                continue
            b = float(r[f"brier_{k}"])
            res[mid] = {"brier": num(b), "accuracy": num(r[f"acc_{k}"]), "brier_skill_vs_market": skill(b, r["brier_market"]),
                        "brier_difference_vs_market": num(b - float(r["brier_market"]))}
        bins.append({"time_bin": f"({lo}, {hi}]", "seconds_lo": lo, "seconds_hi": hi, "n_snapshots": int(r["n"]),
                     "n_markets": {"status": "unavailable", "value": None}, "results": res})

    total = int(d["n"].sum())
    w = d["n"].to_numpy(dtype=float)

    def wavg(col):
        return num(float((d[col].to_numpy(dtype=float) * w).sum() / w.sum())) if total else None

    overall = {"n_snapshots": total,
               "market_baseline": {"brier": wavg("brier_market"), "accuracy": wavg("acc_market")}}
    mb = overall["market_baseline"]["brier"]
    for mid, k in keys.items():
        if mid == "market_baseline":
            continue
        b = wavg(f"brier_{k}")
        overall[mid] = {"brier": b, "accuracy": wavg(f"acc_{k}"),
                        "brier_skill_vs_market": skill(b, mb) if b is not None and mb is not None else None}

    below = {mid: int(sum(1 for r in d.itertuples() if getattr(r, f"brier_{k}") < r.brier_market))
             for mid, k in keys.items() if mid != "market_baseline"}
    diffs = [abs(float(r[f"brier_{k}"]) - float(r["brier_market"])) for _, r in d.iterrows()
             for mid, k in keys.items() if mid != "market_baseline"]
    end = ts(src.df["collected_at_utc"].max())

    return {
        "meta": _meta("prediction_analysis", generated_at, end, SPLIT_UTC, end,
                      {"test_snapshots": total, "time_bins": len(bins), "test_markets": None},
                      src.file_list([PREDICTION_FILE, src.market_csv.name])),
        "evaluation": {
            "unit_of_analysis": "market snapshots (many snapshots per market; correlated, not independent)",
            "evaluation_set": "out-of-sample test markets",
            "split_rule": "Markets whose first snapshot is on or after the split date form the test set; earlier markets are the development set.",
            "test_period_start": SPLIT_UTC, "test_period_end": end,
            "models_fit_on": "development markets only",
            "horizon_seconds_lo": min(b["seconds_lo"] for b in bins) if bins else 0,
            "horizon_seconds_hi": max(b["seconds_hi"] for b in bins) if bins else 0,
            "all_market_exported_models_used": False, "n_test_snapshots": total,
            "n_test_markets": {"status": "unavailable",
                               "reason": "The aggregate results file does not store the number of test markets."}},
        "models": [
            {"id": "market_baseline", "label": "Market baseline",
             "description": "Market-implied probability (quote midpoint) used as the forecast."},
            {"id": "logistic", "label": "Logistic regression", "description": "Regularised logistic model fit on development markets."},
            {"id": "gradient_boosting", "label": "Gradient boosting", "description": "Tree-ensemble model fit on development markets."},
            {"id": "knn_analog", "label": "kNN analog", "description": "Nearest-neighbour analog model fit on development markets."}],
        "by_time_bin": bins,
        "snapshot_weighted_overall": overall,
        "comparison": {
            "time_bins_total": len(bins), "time_bins_model_brier_below_market": below,
            "max_abs_brier_difference_vs_market": num(max(diffs)) if diffs else None,
            "superiority_claim": "none",
            "statement": "Per-bin counts only. No model is claimed superior: differences are small, no significance test or "
                         "market-level clustering is available, and snapshots within a market are correlated."},
        "calibration": {"status": "unavailable",
                        "reason": "Per-prediction records are not stored, so reliability/calibration curves cannot be computed.",
                        "bins": []},
        "limitations": [
            "Only aggregate per-time-bin results are available; individual predictions are not.",
            "Snapshot counts are not market counts; the number of independent markets is unavailable.",
            "No confidence intervals are published because market-level clustering cannot be applied to aggregates.",
            "Accuracy uses a 0.5 probability threshold on resolved outcomes.",
            "Single development/test split over about 12 days; results may not generalise.",
            "Exported all-market models are in-sample and are not used here.",
        ],
    }


# ----------------------------------------------------------------------------- strategy research
def _stat(values) -> dict:
    v = [float(x) for x in values if x is not None and pd.notna(x) and math.isfinite(float(x))]
    if not v:
        return {"n_valid": 0, "min": None, "median": None, "max": None}
    return {"n_valid": len(v), "min": num(min(v)), "median": num(float(np.median(v))), "max": num(max(v))}


def _group_family(fid, label, model, scenario, period, rows) -> dict:
    ev = [r["ev"] for r in rows]
    valid_ev = [x for x in ev if x is not None and math.isfinite(x)]
    ses = [r["se"] for r in rows if r["se"] is not None and math.isfinite(r["se"])]
    return {
        "family_id": fid, "label": label, "model": model, "scenario": scenario, "period": period,
        "n_configurations": len(rows),
        "simulated_trades_per_configuration": _stat(r["n"] for r in rows),
        "win_rate": _stat(r["wr"] for r in rows),
        "ev_per_contract_usd": _stat(ev),
        "share_of_configurations_with_positive_ev": num(sum(1 for x in valid_ev if x > 0) / len(valid_ev), 4) if valid_ev else None,
        "median_ev_standard_error_usd": num(float(np.median(ses))) if ses else None,
        "net_pnl_usd_simulated": _stat(r.get("net") for r in rows),
        "max_drawdown_usd_simulated": _stat(r.get("maxdd") for r in rows),
    }


def build_strategy_research(src: Sources, generated_at: str) -> dict:
    pol = src.sim("pattern_model_policy_grid.csv", STRATEGY_FILES["pattern_model_policy_grid.csv"])
    gate = src.sim("pattern_model_4min_gate.csv", STRATEGY_FILES["pattern_model_4min_gate.csv"])
    gap = src.sim("gap_rule_results.csv", STRATEGY_FILES["gap_rule_results.csv"])
    mom = src.sim("momentum_v2_dev_grid.csv", STRATEGY_FILES["momentum_v2_dev_grid.csv"])

    def f(x):
        return None if pd.isna(x) else float(x)

    groups: dict[tuple, list] = {}

    def add(fid, label, model, scenario, period, n, wr, ev, se, **extra):
        groups.setdefault((fid, label, model, scenario, period), []).append(
            {"n": f(n), "wr": f(wr), "ev": f(ev), "se": f(se), **{k: f(v) for k, v in extra.items()}})

    for _, r in pol.iterrows():
        m = MODEL_IDS[r["model"]]
        L = "Pattern-model entry policy (simulated)"
        add("pattern_model_entry_policy", L, m, "slip_0.01", "dev", r["n_dev"], None, r["ev_dev"], None)
        add("pattern_model_entry_policy", L, m, "slip_0.01", "test", r["n_test"], r["wr_test"], r["ev_test"], r["ev_test_se"])
        add("pattern_model_entry_policy", L, m, "delay_15s", "test", r["n_test_delay"], None, r["ev_test_delay15s"], None)
    for _, r in gate.iterrows():
        m, sc = MODEL_IDS[r["model"]], ("slip_0.01" if r["fill"] == "immediate" else "delay_15s")
        L = "Pattern-model four-minute gate (simulated)"
        add("pattern_model_four_minute_gate", L, m, sc, "dev", r["n_dev"], None, r["ev_dev"], None)
        add("pattern_model_four_minute_gate", L, m, sc, "test", r["n_test"], r["wr_test"], r["ev_test"], r["ev_test_se"])
    for _, r in gap.iterrows():
        sc = "slip_0.01" if r["fill"] == "immediate" else "delay_15s"
        add("gap_rule", "Gap rule (simulated)", None, sc, r["period"], r["n"], r["wr"], r["ev_per_contract"], r["se"])
    for _, r in mom.iterrows():
        n = float(r["n"])
        add("momentum_filter", "Momentum filter (simulated, development period only)", None, "slip_0.01", "dev", n,
            float(r["wins"]) / n if n else None, float(r["net"]) / (n * N_CONTRACTS_MOMENTUM) if n else None, None,
            net=r["net"], maxdd=r["maxdd"])

    families = [_group_family(k[0], k[1], k[2], k[3], k[4], rows) for k, rows in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]
    end = ts(src.df["collected_at_utc"].max())
    names = list(STRATEGY_FILES) + [src.market_csv.name]
    return {
        "meta": _meta("strategy_research", generated_at, end, None, end,
                      {"family_rows": len(families), "configurations_summarised": int(len(pol) + len(gate) + len(gap) + len(mom))},
                      src.file_list(names)),
        "results_type": {"kind": "simulated", "live_trading_data_included": False,
                         "description": "Backtest replays on historical snapshots with explicit fee and slippage assumptions. "
                                        "No live orders, fills, balances or account data are used."},
        "assumptions": {
            "fee_formula": "fee_rate * contracts * price * (1 - price), unrounded (as in the existing research simulations)",
            "fee_rate": KALSHI_FEE_RATE, "fee_rounding": "none; the exchange rounds fees up to a cent grid, so real fees differ slightly",
            "slippage_usd": SLIPPAGE_USD,
            "delayed_fill_scenario": "Entry price taken 15 seconds after the signal (delay_15s) in addition to the slip_0.01 scenario.",
            "contracts_per_trade_momentum_filter": N_CONTRACTS_MOMENTUM,
            "dev_test_split": f"development = markets first seen before {SPLIT_UTC}; test = on or after",
            "fill_model": "Taker fill at the observed ask plus slippage, capped at 0.99; no queue or partial-fill modelling."},
        "families": families,
        "equity_curve": {"status": "unavailable",
                         "reason": "Only aggregate grid results are stored; per-trade P&L sequences are not available."},
        "selection_note": "Each row summarises a distribution across a grid of simulated configurations (median/min/max). "
                          "No single best configuration is selected or published, and ranges on the test period are not "
                          "unbiased performance estimates because the same test set was used to compare configurations.",
        "limitations": [
            "Simulated results only; live trading outcomes are excluded and are not comparable.",
            "Win rate and standard error are unavailable where the source file does not provide them (null).",
            "Net P&L and drawdown exist only for the development-period momentum grid, which assumes 5 contracts per trade.",
            "Trades from overlapping configurations are heavily correlated; configuration counts are not independent samples.",
            "Strategy parameters and thresholds are intentionally withheld.",
            "Short sample window; multiple-comparison bias applies to any selection across configurations.",
        ],
    }


BUILDERS = {
    "market_overview": build_market_overview,
    "technical_indicators": build_technical_indicators,
    "prediction_analysis": build_prediction_analysis,
    "strategy_research": build_strategy_research,
}
