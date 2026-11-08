#!/usr/bin/env python3
"""Generate small, deterministic example inputs for public tests.

This public script intentionally does not call Kalshi, CF Benchmarks, a private API,
the user's Downloads folder, or any credential store.  It writes synthetic records
under ``data/example`` by default and never modifies ``data/raw``.

Usage:
    python scripts/update_data.py
    python scripts/update_data.py --output-dir /tmp/kxbtc15m-example
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "example"
PRIVATE_RAW = (ROOT / "data" / "raw").resolve()

MARKET_COLUMNS = [
    "id", "ticker", "collected_at_utc", "source_timestamp",
    "yes_bid_usd", "yes_ask_usd", "no_bid_usd", "no_ask_usd",
    "last_price_usd", "volume_contracts", "status", "close_time",
    "reference_price_usd", "reference_source", "reference_timestamp",
    "btc_price_difference_usd", "btc_price_difference_pct", "seconds_until_close",
    "floor_strike", "cap_strike", "official_settlement_result",
    "official_final_btc_price_usd", "settlement_status", "settlement_timestamp",
]

ORDER_COLUMNS = [
    "id", "run_id", "strategy_id", "market_ticker", "side", "entry_mode",
    "intended_at", "manual_intent_id", "client_order_id", "exchange_order_id",
    "status", "requested_contracts", "filled_contracts", "average_fill_price_usd",
    "fill_cost_usd", "fees_usd", "maximum_cost_usd", "settlement_result",
    "realized_pnl_usd", "balance_after_settlement_usd", "settled_at",
    "error_code", "error_message",
]


def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def market_rows() -> list[dict[str, object]]:
    """Return two synthetic 15-minute markets sampled every 15 seconds."""
    rows: list[dict[str, object]] = []
    specifications = [
        ("KXBTC15M-EXAMPLE-YES", datetime(2030, 1, 1, 0, 15, tzinfo=timezone.utc), 100_000.0, 1),
        ("KXBTC15M-EXAMPLE-NO", datetime(2030, 1, 1, 0, 30, tzinfo=timezone.utc), 100_100.0, -1),
    ]
    row_id = 1
    for ticker, close, strike, direction in specifications:
        final_price = strike + direction * 45.0
        result = "yes" if final_price >= strike else "no"
        for seconds in range(900, -1, -15):
            ts = close - timedelta(seconds=seconds)
            progress = (900 - seconds) / 900
            wave = 18.0 * math.sin(progress * 4 * math.pi)
            reference = strike + direction * (8.0 + 37.0 * progress) + wave
            probability = min(0.98, max(0.02, 0.5 + (reference - strike) / 200.0))
            rows.append({
                "id": row_id,
                "ticker": ticker,
                "collected_at_utc": iso(ts),
                "source_timestamp": iso(ts),
                "yes_bid_usd": round(max(0.01, probability - 0.01), 3),
                "yes_ask_usd": round(probability, 3),
                "no_bid_usd": round(max(0.01, 1.0 - probability - 0.01), 3),
                "no_ask_usd": round(1.0 - probability, 3),
                "last_price_usd": round(probability, 3),
                "volume_contracts": 1000 + row_id,
                "status": "closed" if seconds == 0 else "active",
                "close_time": iso(close),
                "reference_price_usd": round(reference, 2),
                "reference_source": "synthetic_test_fixture",
                "reference_timestamp": iso(ts),
                "btc_price_difference_usd": round(reference - strike, 2),
                "btc_price_difference_pct": round(100 * (reference - strike) / strike, 6),
                "seconds_until_close": float(seconds),
                "floor_strike": strike,
                "cap_strike": "",
                "official_settlement_result": result,
                "official_final_btc_price_usd": final_price,
                "settlement_status": "finalized",
                "settlement_timestamp": iso(close + timedelta(seconds=2)),
            })
            row_id += 1
    return rows


def order_rows() -> list[dict[str, object]]:
    close_yes = datetime(2030, 1, 1, 0, 15, tzinfo=timezone.utc)
    close_no = datetime(2030, 1, 1, 0, 30, tzinfo=timezone.utc)
    base = {
        "run_id": "example-run",
        "strategy_id": "five_minute_momentum_v1",
        "entry_mode": "momentum_standard",
        "manual_intent_id": "",
        "exchange_order_id": "",
        "status": "settled",
        "requested_contracts": 1,
        "filled_contracts": 1,
        "average_fill_price_usd": 0.6,
        "fill_cost_usd": 0.6,
        "fees_usd": 0.0168,
        "maximum_cost_usd": 0.7,
        "settlement_result": "won",
        "realized_pnl_usd": 0.3832,
        "balance_after_settlement_usd": "",
        "error_code": "",
        "error_message": "synthetic test fixture",
    }
    return [
        {
            **base,
            "id": 1,
            "market_ticker": "KXBTC15M-EXAMPLE-YES",
            "side": "yes",
            "intended_at": iso(close_yes - timedelta(seconds=240)),
            "client_order_id": "example-client-1",
            "settled_at": iso(close_yes + timedelta(seconds=2)),
        },
        {
            **base,
            "id": 2,
            "market_ticker": "KXBTC15M-EXAMPLE-NO",
            "side": "no",
            "intended_at": iso(close_no - timedelta(seconds=240)),
            "client_order_id": "example-client-2",
            "settled_at": iso(close_no + timedelta(seconds=2)),
        },
    ]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def validate(markets: list[dict[str, object]], orders: list[dict[str, object]]) -> None:
    if len(markets) != 122 or len({row["ticker"] for row in markets}) != 2:
        raise ValueError("example markets must contain two complete 61-snapshot series")
    if len({row["id"] for row in markets}) != len(markets):
        raise ValueError("duplicate example market row id")
    if any(row["reference_source"] != "synthetic_test_fixture" for row in markets):
        raise ValueError("example data must remain explicitly synthetic")
    if len(orders) != 2 or len({row["id"] for row in orders}) != 2:
        raise ValueError("example orders must contain two unique rows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output == PRIVATE_RAW or PRIVATE_RAW in output.parents:
        print("ERROR: the public example generator refuses to write into data/raw", file=sys.stderr)
        return 2

    markets = market_rows()
    orders = order_rows()
    validate(markets, orders)
    market_path = output / "KXBTC15M_all.csv"
    order_path = output / "live_orders_all.csv"
    write_csv(market_path, MARKET_COLUMNS, markets)
    write_csv(order_path, ORDER_COLUMNS, orders)
    print(f"wrote synthetic market fixture: {market_path} ({len(markets)} rows)")
    print(f"wrote synthetic order fixture: {order_path} ({len(orders)} rows)")
    print("source: synthetic_test_fixture; no network, credentials, or private files used")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
