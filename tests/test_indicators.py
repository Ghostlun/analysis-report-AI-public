import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import indicators as ind  # noqa: E402


def S(values):
    return pd.Series(values, dtype="float64")


class IndicatorTests(unittest.TestCase):
    def test_sma_values_and_warmup(self):
        r = ind.sma(S([1, 2, 3, 4, 5]), 3)
        self.assertTrue(r.iloc[:2].isna().all())
        self.assertEqual(r.iloc[2:].tolist(), [2.0, 3.0, 4.0])

    def test_no_lookahead(self):
        x = S([1, 2, 3, 4, 5, 6, 7, 8])
        full = ind.ema(x, 3)
        for f in (lambda s: ind.sma(s, 3), lambda s: ind.ema(s, 3), lambda s: ind.rsi(s, 3),
                  lambda s: ind.roc(s, 2), lambda s: ind.realized_volatility(s, 3)):
            a, b = f(x), f(x.iloc[:5])
            np.testing.assert_allclose(a.iloc[:5].to_numpy(), b.to_numpy(), equal_nan=True)
        self.assertEqual(len(full), 8)

    def test_ema_seed_and_recursion(self):
        r = ind.ema(S([1, 2, 3, 4, 5]), 3)
        self.assertTrue(r.iloc[:2].isna().all())
        self.assertAlmostEqual(r.iloc[2], 2.0)             # SMA seed
        self.assertAlmostEqual(r.iloc[3], 0.5 * 4 + 0.5 * 2.0)
        self.assertAlmostEqual(r.iloc[4], 0.5 * 5 + 0.5 * 3.0)

    def test_pct_return_and_roc(self):
        r = ind.pct_return(S([100, 110, 99]))
        self.assertTrue(np.isnan(r.iloc[0]))
        self.assertAlmostEqual(r.iloc[1], 10.0)
        self.assertAlmostEqual(r.iloc[2], -10.0)
        self.assertAlmostEqual(ind.roc(S([100, 105, 120]), 2).iloc[2], 20.0)

    def test_rsi_wilder_reference_values(self):
        # classic Wilder example: 14-period RSI of this close series
        c = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        r = ind.rsi(S(c), 14)
        self.assertTrue(r.iloc[:14].isna().all())
        self.assertAlmostEqual(r.iloc[14], 70.46, places=1)

    def test_rsi_smoothing_step(self):
        c = S([1, 2, 1, 2, 3, 2])
        r = ind.rsi(c, 2)
        # seed: gains [1,0] -> 0.5, losses [0,1] -> 0.5 => RSI 50
        self.assertAlmostEqual(r.iloc[2], 50.0)
        ag, al = (0.5 * 1 + 1) / 2, (0.5 * 1 + 0) / 2    # step to price 2 (gain 1)
        self.assertAlmostEqual(r.iloc[3], 100 - 100 / (1 + ag / al))

    def test_rsi_edge_cases(self):
        self.assertTrue((ind.rsi(S([5] * 10), 3).iloc[3:] == 50.0).all())          # flat -> neutral
        self.assertTrue((ind.rsi(S(np.arange(1, 11)), 3).iloc[3:] == 100.0).all())  # only gains
        self.assertTrue((ind.rsi(S(np.arange(10, 0, -1)), 3).iloc[3:] == 0.0).all())  # only losses

    def test_insufficient_history_is_unavailable(self):
        short = S([1, 2, 3])
        for f in (lambda: ind.sma(short, 5), lambda: ind.ema(short, 5), lambda: ind.rsi(short, 3),
                  lambda: ind.realized_volatility(short, 3), lambda: ind.roc(short, 3)):
            self.assertTrue(f().isna().all())

    def test_empty_series(self):
        for f in (ind.sma, ind.ema, ind.rsi, ind.roc, ind.realized_volatility):
            self.assertEqual(len(f(S([]), 3)), 0)

    def test_realized_volatility_value_zero_and_annualization(self):
        c = S([100, 101, 100, 101])
        r = np.diff(np.log(c))
        v = ind.realized_volatility(c, 3)
        self.assertTrue(v.iloc[:3].isna().all())
        self.assertAlmostEqual(v.iloc[3], 100 * np.sqrt(np.mean(r ** 2)))
        va = ind.realized_volatility(c, 3, annualize_bars_per_year=ind.bars_per_year(60))
        self.assertAlmostEqual(va.iloc[3], v.iloc[3] * np.sqrt(8760))
        z = ind.realized_volatility(S([7] * 6), 3)
        self.assertTrue((z.iloc[3:] == 0.0).all())  # zero volatility is valid, not NaN

    def test_invalid_inputs_never_produce_inf(self):
        c = S([1, 0, 2, 3, -1, 4, np.inf, 5, 6, 7, 8])
        for f in (lambda: ind.sma(c, 2), lambda: ind.ema(c, 2), lambda: ind.rsi(c, 2), lambda: ind.roc(c, 1),
                  lambda: ind.realized_volatility(c, 2)):
            self.assertFalse(np.isinf(f().to_numpy()).any())
        self.assertTrue(ind.sma(c, 2).iloc[[1, 4, 6]].isna().all())

    def test_segments_restart_warmup_and_do_not_span(self):
        c = S([1, 2, 3, 100, 101, 102])
        seg = pd.Series([0, 0, 0, 1, 1, 1])
        r = ind.sma(c, 3, seg)
        self.assertEqual(r.iloc[2], 2.0)
        self.assertTrue(np.isnan(r.iloc[3]) and np.isnan(r.iloc[4]))
        self.assertEqual(r.iloc[5], 101.0)
        self.assertTrue(np.isnan(ind.roc(c, 1, seg).iloc[3]))  # no return across the segment break

    def test_nan_breaks_run(self):
        c = S([1, 2, np.nan, 4, 5, 6])
        r = ind.sma(c, 2)
        self.assertTrue(np.isnan(r.iloc[2]) and np.isnan(r.iloc[3]))
        self.assertEqual(r.iloc[4], 4.5)

    def test_bad_windows(self):
        for bad in (0, -1, 2.5):
            with self.assertRaises(ValueError):
                ind.sma(S([1, 2, 3]), bad)
        with self.assertRaises(ValueError):
            ind.bars_per_year(0)

    def test_compute_indicators_excludes_partial_and_requires_bar_minutes(self):
        bars = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0], "partial": [False] * 4 + [True], "segment": [1] * 5})
        out = ind.compute_indicators(bars, sma_windows=(2,), ema_windows=(2,), rsi_window=2, roc_windows=(1,), vol_windows=(2,))
        self.assertTrue(np.isnan(out["close"].iloc[4]))
        self.assertTrue(np.isnan(out["sma_2"].iloc[4]))
        self.assertEqual(out["sma_2"].iloc[3], 3.5)
        self.assertIn("realized_vol_2_bar_pct", out.columns)
        gap = bars.assign(partial=False, gap_affected=[False, False, True, False, False])
        og = ind.compute_indicators(gap, sma_windows=(2,), ema_windows=(2,), rsi_window=2, roc_windows=(1,), vol_windows=(2,))
        self.assertTrue(np.isnan(og["close"].iloc[2]))
        self.assertTrue(np.isnan(og["sma_2"].iloc[3]))  # warm-up restarts after the gap-affected bar
        self.assertEqual(og["sma_2"].iloc[4], 4.5)
        with self.assertRaises(ValueError):
            ind.compute_indicators(bars, annualize=True)
        out2 = ind.compute_indicators(bars, annualize=True, bar_minutes=1, vol_windows=(2,))
        self.assertIn("realized_vol_2_ann_pct", out2.columns)

    def test_no_atr_or_volume_indicators_exposed(self):
        for name in ("atr", "vwap", "obv"):
            self.assertFalse(hasattr(ind, name))


if __name__ == "__main__":
    unittest.main()
