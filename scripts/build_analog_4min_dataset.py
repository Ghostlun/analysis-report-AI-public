#!/usr/bin/env python3
"""Build analog_4min_v1 artifacts from recorded KXBTC15M BRTI snapshots.

The script is deterministic, offline, and never interpolates or fabricates prices.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "raw" / "KXBTC15M_all.csv"
OUT = ROOT / "outputs" / "analog_4min_v1"

FEATURES = ["z", "sec", "d2", "d4", "d8", "d12", "d20"]
LAGS = (2, 4, 8, 12, 20)
SIGMA_FLOOR = 0.0001
SNAPSHOT_SECONDS = 15
EVAL_SECONDS = 240
EVAL_WINDOW = (225, 255)


def iso_z(ts: pd.Timestamp) -> str:
    return ts.tz_convert(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_features(prices: list[float], strike: float, sec: float) -> dict[str, float]:
    pcts = [100.0 * math.log(p / strike) for p in prices]
    window = pcts[-21:]
    changes = np.diff(np.asarray(window, dtype=float))
    sigma = max(float(np.std(changes, ddof=0)), SIGMA_FLOOR)
    now = window[-1]
    result = {
        "z": now / (sigma * math.sqrt(max(sec, 1.0) / SNAPSHOT_SECONDS)),
        "sec": float(sec),
    }
    for lag in LAGS:
        result[f"d{lag}"] = (now - window[-1 - lag]) / (sigma * math.sqrt(lag))
    return result


def expected_grid(close: pd.Timestamp, start_sec: int, end_sec: int) -> list[pd.Timestamp]:
    return [close - pd.Timedelta(seconds=s) for s in range(start_sec, end_sec - 1, -SNAPSHOT_SECONDS)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SOURCE)
    source_rows = len(df)
    source_tickers = int(df["ticker"].nunique())

    for col in ("collected_at_utc", "reference_timestamp", "close_time"):
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    df["reference_price_usd"] = pd.to_numeric(df["reference_price_usd"], errors="coerce")
    df["floor_strike"] = pd.to_numeric(df["floor_strike"], errors="coerce")
    df["seconds_until_close"] = pd.to_numeric(df["seconds_until_close"], errors="coerce")
    df["official_settlement_result"] = df["official_settlement_result"].str.lower()
    all_reference_start = df["reference_timestamp"].min()
    all_reference_end = df["reference_timestamp"].max()
    all_close_start = df["close_time"].min()
    all_close_end = df["close_time"].max()

    raw_markets: list[dict] = []
    train_rows: list[dict[str, float | int]] = []
    excluded_raw: Counter[str] = Counter()
    excluded_train: Counter[str] = Counter()
    missing_gap_markets = 0
    missing_gap_count = 0
    duplicate_timestamps_removed = 0
    invalid_prices_removed = 0
    valid_settled_markets = 0
    raw_timestamps: list[pd.Timestamp] = []

    for ticker, group in df.groupby("ticker", sort=True):
        group = group.sort_values("collected_at_utc").copy()
        results = group["official_settlement_result"].dropna().unique().tolist()
        if not results or results[0] not in ("yes", "no"):
            excluded_raw["unsettled_or_missing_result"] += 1
            continue
        result = results[0]
        if any(r != result for r in results):
            excluded_raw["conflicting_results"] += 1
            continue

        strikes = group.loc[group["floor_strike"] > 0, "floor_strike"].dropna().unique()
        closes = group["close_time"].dropna().unique()
        if len(strikes) != 1:
            excluded_raw["missing_or_conflicting_strike"] += 1
            continue
        if len(closes) != 1:
            excluded_raw["missing_or_conflicting_close_time"] += 1
            continue
        strike = float(strikes[0])
        close = pd.Timestamp(closes[0])
        valid_settled_markets += 1

        source_rows_market = group[group["reference_source"].eq("cf_benchmarks_brti")].copy()
        invalid_prices_removed += int((source_rows_market["reference_price_usd"].isna() |
                                       (source_rows_market["reference_price_usd"] <= 0)).sum())
        points = source_rows_market[
            source_rows_market["reference_timestamp"].notna()
            & source_rows_market["reference_price_usd"].notna()
            & (source_rows_market["reference_price_usd"] > 0)
        ].copy()
        before_dedup = len(points)
        points = points.sort_values(["reference_timestamp", "collected_at_utc"]).drop_duplicates(
            "reference_timestamp", keep="last"
        )
        duplicate_timestamps_removed += before_dedup - len(points)
        points = points[
            (points["reference_timestamp"] >= close - pd.Timedelta(minutes=15))
            & (points["reference_timestamp"] <= close)
        ].copy()

        point_map = dict(zip(points["reference_timestamp"], points["reference_price_usd"]))
        required = expected_grid(close, 300, 240)
        if not all(ts in point_map for ts in required):
            excluded_raw["missing_required_5m_to_4m_window"] += 1
            continue

        full_grid = expected_grid(close, 900, 0)
        missing = sum(ts not in point_map for ts in full_grid)
        if missing:
            missing_gap_markets += 1
            missing_gap_count += missing

        prices_json = [
            {"timestamp": iso_z(ts), "price": float(price)}
            for ts, price in sorted(point_map.items())
        ]
        raw_timestamps.extend(point_map)
        raw_markets.append({
            "market_ticker": ticker,
            "close_time": iso_z(close),
            "floor_strike": strike,
            "result": result,
            "price_source": "BRTI (CF Benchmarks; source field cf_benchmarks_brti)",
            "prices": prices_json,
        })

        # Use the collector observation closest to 240 seconds, as the live model does.
        candidates = group[
            group["seconds_until_close"].between(*EVAL_WINDOW, inclusive="both")
            & group["reference_source"].eq("cf_benchmarks_brti")
            & group["reference_timestamp"].notna()
            & group["reference_price_usd"].notna()
            & (group["reference_price_usd"] > 0)
        ].copy()
        if candidates.empty:
            excluded_train["no_observation_in_225_255s_window"] += 1
            continue
        candidates["distance_to_240"] = (candidates["seconds_until_close"] - EVAL_SECONDS).abs()
        evaluation = candidates.sort_values(["distance_to_240", "collected_at_utc"]).iloc[0]
        eval_ts = evaluation["reference_timestamp"]
        history_grid = [eval_ts - pd.Timedelta(seconds=s) for s in range(300, -1, -SNAPSHOT_SECONDS)]
        if not all(ts in point_map for ts in history_grid):
            excluded_train["fewer_than_21_contiguous_15s_snapshots"] += 1
            continue
        history_prices = [float(point_map[ts]) for ts in history_grid]
        features = compute_features(history_prices, strike, float(evaluation["seconds_until_close"]))
        train_rows.append({**features, "y": 1 if result == "yes" else 0})

    raw_markets.sort(key=lambda x: (x["close_time"], x["market_ticker"]))
    raw_path = OUT / "raw_analog_markets.json"
    raw_path.write_text(json.dumps(raw_markets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    train_path = OUT / "analog_model_train.csv"
    with train_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FEATURES + ["y"])
        writer.writeheader()
        for row in train_rows:
            writer.writerow({name: format(float(row[name]), ".15g") for name in FEATURES} |
                            {"y": int(row["y"])})

    matrix = np.asarray([[float(row[name]) for name in FEATURES] for row in train_rows], dtype=float)
    if len(matrix) == 0:
        raise RuntimeError("No training rows were produced")
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0, ddof=0)
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(means)) or not np.all(np.isfinite(scales)):
        raise RuntimeError("Non-finite model value detected")
    if np.any(scales <= 0):
        raise RuntimeError(f"Zero scaler scale detected: {dict(zip(FEATURES, scales))}")
    model = {
        "features": FEATURES,
        "scaler_mean": [float(x) for x in means],
        "scaler_scale": [float(x) for x in scales],
        "k": 150,
    }
    model_path = OUT / "analog_model.json"
    model_path.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")

    source_start = min(raw_timestamps) if raw_timestamps else pd.NaT
    source_end = max(raw_timestamps) if raw_timestamps else pd.NaT
    yes_count = sum(int(row["y"]) for row in train_rows)
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (raw_path, train_path, model_path)
    }
    summary = f"""# analog_4min_v1 data validation summary

## Source and scope

- Source file: `data/raw/KXBTC15M_all.csv`
- Recorded reference source: `cf_benchmarks_brti` (CF Benchmarks BRTI)
- Full local reference timestamp range: {iso_z(all_reference_start)} through {iso_z(all_reference_end)}
- Full local market close range: {iso_z(all_close_start)} through {iso_z(all_close_end)}
- BRTI observation range included in the raw output: {iso_z(source_start)} through {iso_z(source_end)}
- Source rows: {source_rows:,}
- Source markets: {source_tickers:,}
- No interpolation or synthetic prices were used.
- Raw JSON contains positive, de-duplicated BRTI observations from 15 minutes before close through close, sorted by UTC timestamp.

## Market coverage

- Settled markets with valid ticker, strike, close time and result: {valid_settled_markets:,}
- Markets included in `raw_analog_markets.json`: {len(raw_markets):,}
- Markets included in `analog_model_train.csv`: {len(train_rows):,}
- Training labels: YES={yes_count:,}, NO={len(train_rows) - yes_count:,}
- Markets with one or more missing points on the exact 15-second close-minus-15m to close grid: {missing_gap_markets:,}
- Total missing exact-grid points across included markets: {missing_gap_count:,}
- Duplicate reference timestamps removed: {duplicate_timestamps_removed:,}
- Non-positive or missing BRTI prices removed: {invalid_prices_removed:,}

## Exclusions from raw JSON

{chr(10).join(f'- {key}: {value:,}' for key, value in sorted(excluded_raw.items())) or '- None'}

## Additional exclusions from training CSV

{chr(10).join(f'- {key}: {value:,}' for key, value in sorted(excluded_train.items())) or '- None'}

## Feature construction

- Evaluation observation: collector row closest to 240 seconds before close, restricted to 225–255 seconds.
- Snapshot series: 21 exact, contiguous 15-second BRTI timestamps ending at the evaluation row's reference timestamp.
- `pct = 100 * ln(reference_price / floor_strike)`.
- `sigma`: population standard deviation (`ddof=0`) of the 20 changes, floored at 0.0001.
- Features: `z, sec, d2, d4, d8, d12, d20`; label `y` is YES=1 and NO=0.
- Scaler: population mean and standard deviation (`ddof=0`) over the training feature rows.

## Integrity checks

- Training columns are exactly: `{','.join(FEATURES + ['y'])}`.
- All training features and scaler values are finite.
- All scaler scales are positive.
- Model `k`: 150.
- `raw_analog_markets.json` SHA-256: `{hashes[raw_path.name]}`
- `analog_model_train.csv` SHA-256: `{hashes[train_path.name]}`
- `analog_model.json` SHA-256: `{hashes[model_path.name]}`

## Limitation

The local source ends at {iso_z(source_end)}. It does not contain markets after that timestamp, so this build does not claim coverage through the current date.
"""
    summary_path = OUT / "DATA_VALIDATION.md"
    summary_path.write_text(summary, encoding="utf-8")

    print(json.dumps({
        "output_dir": str(OUT),
        "raw_markets": len(raw_markets),
        "training_rows": len(train_rows),
        "yes": yes_count,
        "no": len(train_rows) - yes_count,
        "excluded_raw": dict(excluded_raw),
        "excluded_train": dict(excluded_train),
        "missing_gap_markets": missing_gap_markets,
        "source_period": [iso_z(source_start), iso_z(source_end)],
    }, indent=2))


if __name__ == "__main__":
    main()
