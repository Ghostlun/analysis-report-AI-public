import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import data_loader as dl  # noqa: E402


def make_raw(rows):
    """rows: (ticker, collected, ref_ts, ref_price) tuples -> minimal synthetic raw frame."""
    return pd.DataFrame({
        "ticker": [r[0] for r in rows],
        "collected_at_utc": [r[1] for r in rows],
        "reference_timestamp": [r[2] for r in rows],
        "reference_price_usd": [r[3] for r in rows],
        "floor_strike": 100.0,
        "close_time": "2026-01-01T00:15:00Z",
    })


def ref_series(times, prices):
    t = pd.to_datetime(times, utc=True)
    return dl.ReferenceSeries(pd.DataFrame({
        "reference_timestamp": t, "reference_price_usd": np.asarray(prices, float),
        "first_collected_at_utc": t, "n_source_rows": 1}), pd.DataFrame(), 0)


class LoaderTests(unittest.TestCase):
    def test_missing_required_column(self):
        raw = make_raw([("A", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 1.0)]).drop(columns=["reference_price_usd"])
        with self.assertRaises(dl.DataValidationError):
            dl.clean_market_frame(raw)

    def test_invalid_timestamps_counted_and_mixed_formats(self):
        raw = make_raw([
            ("A", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00.123456+00:00", 10.0),
            ("A", "2026-01-01T00:00:15.5Z", "garbage", 11.0),
            ("A", "not-a-time", "2026-01-01T00:00:30Z", 12.0),
        ])
        df, c = dl.clean_market_frame(raw)
        self.assertEqual(c["invalid_timestamps"]["reference_timestamp"], 1)
        self.assertEqual(c["invalid_timestamps"]["collected_at_utc"], 1)
        self.assertEqual(len(df), 2)  # row without a collection time is dropped
        self.assertEqual(str(df["collected_at_utc"].dt.tz), "UTC")
        # price whose reference timestamp is invalid is not usable
        self.assertTrue(df["reference_price_usd"].isna().sum() == 1)

    def test_sorted_chronologically(self):
        raw = make_raw([("A", "2026-01-01T00:00:30Z", "2026-01-01T00:00:30Z", 3.0),
                        ("A", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 1.0)])
        df, _ = dl.clean_market_frame(raw)
        self.assertTrue(df["collected_at_utc"].is_monotonic_increasing)

    def test_invalid_numeric_and_nonpositive_reference(self):
        raw = make_raw([("A", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "abc"),
                        ("A", "2026-01-01T00:00:15Z", "2026-01-01T00:00:15Z", -5.0),
                        ("A", "2026-01-01T00:00:30Z", "2026-01-01T00:00:30Z", float("inf"))])
        raw["yes_bid_usd"] = [0.5, 1.5, 0.2]
        df, c = dl.clean_market_frame(raw)
        self.assertTrue(df["reference_price_usd"].isna().all())
        self.assertEqual(c["non_positive_reference_prices"], 1)
        self.assertEqual(c["out_of_range_contract_prices"], 1)

    def test_empty_dataset(self):
        raw = make_raw([]).astype({"ticker": object})
        df, _ = dl.clean_market_frame(raw)
        rs = dl.build_reference_series(df)
        self.assertTrue(rs.data.empty)
        self.assertTrue(dl.resample_reference(rs, "1m").empty)

    def test_missing_reference_prices_not_filled(self):
        raw = make_raw([("A", "2026-01-01T00:00:00Z", None, None),
                        ("A", "2026-01-01T00:00:15Z", "2026-01-01T00:00:15Z", 5.0),
                        ("A", "2026-01-01T00:00:30Z", None, None)])
        df, _ = dl.clean_market_frame(raw)
        rs = dl.build_reference_series(df)
        self.assertEqual(len(rs.data), 1)

    def test_duplicate_reference_timestamps_collapse_by_reference_not_collection_time(self):
        raw = make_raw([("A", "2026-01-01T00:00:01Z", "2026-01-01T00:00:00Z", 10.0),
                        ("B", "2026-01-01T00:00:02Z", "2026-01-01T00:00:00Z", 10.0),
                        ("A", "2026-01-01T00:00:16Z", "2026-01-01T00:00:15Z", 11.0)])
        rs = dl.build_reference_series(dl.clean_market_frame(raw)[0])
        self.assertEqual(len(rs.data), 2)
        self.assertEqual(rs.duplicate_rows_removed, 1)
        self.assertTrue(rs.conflicts.empty)
        self.assertEqual(rs.data["n_source_rows"].tolist(), [2, 1])

    def test_conflicting_duplicates_deterministic_and_reported(self):
        rows = [("A", "2026-01-01T00:00:05Z", "2026-01-01T00:00:00Z", 12.0),
                ("B", "2026-01-01T00:00:01Z", "2026-01-01T00:00:00Z", 10.0),
                ("C", "2026-01-01T00:00:03Z", "2026-01-01T00:00:00Z", 11.0)]
        a = dl.build_reference_series(dl.clean_market_frame(make_raw(rows))[0])
        b = dl.build_reference_series(dl.clean_market_frame(make_raw(rows[::-1]))[0])
        self.assertEqual(a.data["reference_price_usd"].tolist(), [10.0])  # earliest collected wins
        self.assertEqual(b.data["reference_price_usd"].tolist(), [10.0])
        self.assertEqual(len(a.conflicts), 1)
        self.assertEqual(a.conflicts.iloc[0]["n_distinct_prices"], 3)
        self.assertEqual(a.conflicts.iloc[0]["max_price"], 12.0)

    def test_detect_gaps(self):
        t = pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:15Z", "2026-01-01T00:10:15Z",
                            "2026-01-01T00:10:30Z"], utc=True)
        g = dl.detect_gaps(pd.Series(t), 300)
        self.assertEqual(len(g), 1)
        self.assertEqual(g.iloc[0]["gap_seconds"], 600.0)
        self.assertTrue(dl.detect_gaps(pd.Series(t[:1]), 300).empty)

    def test_resample_close_and_boundaries(self):
        # observations every 15 s from 00:00:15 to 00:03:00 -> 1m bars end at 00:01, 00:02, 00:03
        times = pd.date_range("2026-01-01T00:00:15Z", "2026-01-01T00:03:00Z", freq="15s")
        rs = ref_series(times, np.arange(len(times)) + 100.0)
        bars = dl.resample_reference(rs, "1m")
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars.index[0], pd.Timestamp("2026-01-01T00:01:00Z"))
        self.assertEqual(bars["close"].tolist(), [103.0, 107.0, 111.0])  # obs at exactly :00 belongs to bar ending then
        self.assertEqual(bars["n_obs"].tolist(), [4, 4, 4])
        self.assertTrue((bars["last_obs_time"] <= bars.index).all())  # no look-ahead
        self.assertFalse(bars["partial"].any())
        self.assertEqual(bars["segment"].nunique(), 1)

    def test_incomplete_bars_marked(self):
        times = pd.date_range("2026-01-01T00:00:40Z", "2026-01-01T00:02:30Z", freq="10s")
        bars = dl.resample_reference(ref_series(times, np.arange(len(times)) + 1.0), "5m", max_gap_seconds=60)
        self.assertEqual(len(bars), 1)
        self.assertTrue(bars["partial"].iloc[0])  # 5m bar covers only 00:00:40-00:02:30

    def test_last_bar_partial_but_first_complete(self):
        times = pd.date_range("2026-01-01T00:00:10Z", "2026-01-01T00:02:20Z", freq="10s")
        bars = dl.resample_reference(ref_series(times, np.arange(len(times)) + 1.0), "1m", max_gap_seconds=30)
        self.assertEqual(bars["partial"].tolist(), [False, False, True])

    def test_gap_creates_missing_bars_and_new_segment_without_ffill(self):
        a = pd.date_range("2026-01-01T00:00:15Z", "2026-01-01T00:02:00Z", freq="15s")
        b = pd.date_range("2026-01-01T00:10:15Z", "2026-01-01T00:12:00Z", freq="15s")
        times = a.append(b)
        bars = dl.resample_reference(ref_series(times, np.arange(len(times)) + 1.0), "1m", max_gap_seconds=300)
        self.assertTrue(bars["close"].isna().any())
        self.assertEqual(int(bars["n_obs"].isna().sum()), 0)
        self.assertEqual(bars["segment"].nunique(), 2)  # two runs separated by missing bars
        missing = bars[bars["close"].isna()]
        self.assertTrue((missing["n_obs"] == 0).all())
        self.assertTrue(bars["gap_affected"].any())

    def test_gap_inside_one_bar_is_flagged(self):
        a = pd.date_range("2026-01-01T00:00:30Z", "2026-01-01T00:20:00Z", freq="30s")
        b = pd.date_range("2026-01-01T00:40:30Z", "2026-01-01T02:00:00Z", freq="30s")
        times = a.append(b)
        bars = dl.resample_reference(ref_series(times, np.arange(len(times)) + 1.0), "1h", max_gap_seconds=300)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars["gap_affected"].tolist(), [True, False])

    def test_gap_between_bars_breaks_segment_without_missing_bar(self):
        a = pd.date_range("2026-01-01T00:00:30Z", "2026-01-01T00:59:30Z", freq="30s")
        b = pd.date_range("2026-01-01T01:30:30Z", "2026-01-01T02:00:00Z", freq="30s")
        times = a.append(b)
        bars = dl.resample_reference(ref_series(times, np.arange(len(times)) + 1.0), "1h", max_gap_seconds=300)
        self.assertEqual(bars["close"].notna().tolist(), [True, True])
        self.assertEqual(bars["segment"].tolist(), [1, 2])

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            dl.resample_reference(ref_series(["2026-01-01T00:00:00Z"], [1.0]), "2m")

    def test_refuses_live_orders_and_missing_file(self):
        with self.assertRaises(dl.DataValidationError):
            dl.load_market_snapshots("data/raw/live_orders_all.csv")
        with self.assertRaises(dl.DataValidationError):
            dl.load_market_snapshots(Path(tempfile.gettempdir()) / "no_such_market_file.csv")

    def test_load_from_synthetic_csv_keeps_only_allowlisted_columns(self):
        raw = make_raw([("A", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 10.0)])
        raw["secret_extra"] = "x"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "market.csv"
            raw.to_csv(p, index=False)
            df, rep = dl.load_market_snapshots(p)
        self.assertNotIn("secret_extra", df.columns)
        self.assertEqual(rep.rows_read, 1)
        self.assertEqual(len(rep.sha256), 64)
        self.assertEqual(df.attrs["source_file"], "market.csv")


if __name__ == "__main__":
    unittest.main()
