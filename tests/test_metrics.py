import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared import metrics as m  # noqa: E402


class PredictionMetricTests(unittest.TestCase):
    def test_brier(self):
        self.assertAlmostEqual(m.brier_score([0.9, 0.2], [1, 0]), (0.01 + 0.04) / 2)
        self.assertEqual(m.brier_score([1, 0], [1, 0]), 0.0)
        self.assertAlmostEqual(m.brier_score([0.5, 0.5], [1, 0]), 0.25)

    def test_accuracy_threshold_and_nan(self):
        self.assertEqual(m.directional_accuracy([0.5, 0.4, 0.9, np.nan], [1, 1, 1, 0]), 2 / 3)  # 0.5 counts as "yes"

    def test_empty_and_invalid(self):
        self.assertTrue(np.isnan(m.brier_score([], [])))
        self.assertTrue(np.isnan(m.directional_accuracy([], [])))
        self.assertTrue(np.isnan(m.brier_skill_score([], [], [])))
        with self.assertRaises(ValueError):
            m.brier_score([1.2], [1])
        with self.assertRaises(ValueError):
            m.brier_score([0.5], [2])
        with self.assertRaises(ValueError):
            m.brier_score([0.5, 0.5], [1])

    def test_brier_skill(self):
        y = [1, 0, 1, 0]
        base = [0.5] * 4
        self.assertAlmostEqual(m.brier_skill_score([1, 0, 1, 0], base, y), 1.0)
        self.assertAlmostEqual(m.brier_skill_score(base, base, y), 0.0)
        self.assertLess(m.brier_skill_score([0, 1, 0, 1], base, y), 0)
        self.assertTrue(np.isnan(m.brier_skill_score([0.5], [1.0], [1])))  # baseline perfect -> undefined

    def test_wilson_known_values_and_boundaries(self):
        lo, hi = m.wilson_interval(8, 10)
        self.assertAlmostEqual(lo, 0.4902, places=3)
        self.assertAlmostEqual(hi, 0.9433, places=3)
        lo0, hi0 = m.wilson_interval(0, 10)
        self.assertEqual(lo0, 0.0)
        self.assertGreater(hi0, 0)
        lo1, hi1 = m.wilson_interval(10, 10)
        self.assertEqual(hi1, 1.0)
        self.assertTrue(all(np.isnan(v) for v in m.wilson_interval(0, 0)))
        with self.assertRaises(ValueError):
            m.wilson_interval(5, 4)

    def test_wilson_matches_existing_implementation(self):
        sys.path.insert(0, str(ROOT / "src"))
        import momentum
        for k, n in [(0, 5), (3, 7), (50, 100), (99, 100), (1, 1)]:
            a, b = m.wilson_interval(k, n), momentum.wilson(k, n)
            np.testing.assert_allclose(a, b, atol=1e-12)
        self.assertEqual(m.KALSHI_FEE_RATE, momentum.FEE_RATE)

    def test_sample_counts_distinguish_snapshots_and_markets(self):
        df = pd.DataFrame({"ticker": ["A", "A", "B", None]})
        self.assertEqual(m.sample_counts(df), {"n_snapshots": 4, "n_markets": 2})
        self.assertEqual(m.sample_counts(df.drop(columns="ticker"))["n_markets"], None)

    def test_market_level_evaluation(self):
        # market A has 9 snapshots, market B has 1: snapshot pooling and market averaging must differ
        df = pd.DataFrame({"ticker": ["A"] * 9 + ["B"], "p": [1.0] * 9 + [0.0], "y": [1] * 9 + [1], "base": [0.5] * 10})
        r = m.evaluate_predictions(df, "p", "y", "base")
        self.assertEqual(r["counts"], {"n_snapshots": 10, "n_markets": 2})
        self.assertAlmostEqual(r["brier"], 0.1)
        self.assertAlmostEqual(r["market_level"]["mean"], 0.5)
        self.assertEqual(r["market_level"]["n_clusters"], 2)
        self.assertAlmostEqual(r["brier_skill_vs_baseline"], 1 - 0.1 / 0.25)
        self.assertEqual(r, m.evaluate_predictions(df, "p", "y", "base"))  # deterministic
        self.assertIsNone(m.evaluate_predictions(df.drop(columns="ticker"), "p", "y")["market_level"])

    def test_evaluate_empty(self):
        df = pd.DataFrame({"ticker": [], "p": [], "y": []})
        r = m.evaluate_predictions(df, "p", "y")
        self.assertEqual(r["counts"]["n_snapshots"], 0)
        self.assertTrue(np.isnan(r["brier"]))
        self.assertEqual(r["market_level"]["n_clusters"], 0)


class SimulatedTradeTests(unittest.TestCase):
    def test_fee_formula(self):
        self.assertAlmostEqual(m.kalshi_taker_fee(0.5, 5), 0.07 * 5 * 0.25)
        self.assertAlmostEqual(m.kalshi_taker_fee(0.95, 1), 0.07 * 0.95 * 0.05)

    def test_pnl_win_loss_with_slippage_and_cap(self):
        a = m.TradeAssumptions(contracts_per_trade=5, slippage_usd=0.01)
        win, lose = m.simulate_trade_pnl([0.90, 0.90], [1, 0], a)
        fee = 0.07 * 5 * 0.91 * 0.09
        self.assertAlmostEqual(win, 5 * 0.09 - fee)
        self.assertAlmostEqual(lose, -5 * 0.91 - fee)
        capped = m.simulate_trade_pnl([0.995], [1], a)[0]   # exec price capped at 0.99
        self.assertAlmostEqual(capped, 5 * 0.01 - 0.07 * 5 * 0.99 * 0.01)
        zero_slip = m.simulate_trade_pnl([0.5], [1], m.TradeAssumptions(slippage_usd=0.0))[0]
        self.assertAlmostEqual(zero_slip, 5 * 0.5 - 0.07 * 5 * 0.25)

    def test_pnl_matches_existing_replay(self):
        sys.path.insert(0, str(ROOT / "src"))
        import momentum
        C = pd.DataFrame({"ticker": list("ABCD"), "cur": [0.62, 0.91, 0.97, 0.985], "win": [True, False, True, True]})
        old = momentum.replay(C, slip=0.01)
        a = m.TradeAssumptions(contracts_per_trade=momentum.N_CONTRACTS, slippage_usd=0.01)
        np.testing.assert_allclose(m.simulate_trade_pnl(C["cur"], C["win"], a), old["pnl"].to_numpy(), atol=1e-12)
        self.assertAlmostEqual(m.max_drawdown(old.sort_index()["pnl"]), momentum.summarize(old.assign(t=range(4)))["maxdd"])

    def test_invalid_assumptions_and_prices(self):
        with self.assertRaises(ValueError):
            m.TradeAssumptions(contracts_per_trade=0)
        with self.assertRaises(ValueError):
            m.TradeAssumptions(slippage_usd=-0.1)
        with self.assertRaises(ValueError):
            m.simulate_trade_pnl([1.5], [1])

    def test_max_drawdown(self):
        self.assertEqual(m.max_drawdown([]), 0.0)
        self.assertEqual(m.max_drawdown([1, 2, 3]), 0.0)
        self.assertEqual(m.max_drawdown([-1, -2]), 3.0)             # peak starts at 0
        self.assertEqual(m.max_drawdown([2, -1, -1, 3, -4, 1]), 4.0)  # cum 2,1,0,3,-1,0 -> peak 3 to -1
        self.assertEqual(m.max_drawdown([1, np.nan, -2]), 2.0)

    def test_summary_fields_and_assumptions_preserved(self):
        a = m.TradeAssumptions(contracts_per_trade=2, slippage_usd=0.0, fee_rate=0.0)
        s = m.summarize_simulated_trades([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 1], a, market_ids=["a", "b", "c", "c"])
        self.assertEqual(s["source"], "simulated")
        self.assertEqual(s["assumptions"]["contracts_per_trade"], 2)
        self.assertEqual((s["n_trades"], s["n_markets"], s["wins"]), (4, 3, 3))
        self.assertAlmostEqual(s["win_rate"], 0.75)
        self.assertAlmostEqual(s["net_pnl_usd"], 2 * (0.5 - 0.5 + 0.5 + 0.5) )  # wins +1, loss -1 per trade
        self.assertAlmostEqual(s["ev_per_contract_usd"], 0.5 * 0.5)
        self.assertAlmostEqual(s["max_drawdown_usd"], 1.0)
        lo, hi = m.wilson_interval(3, 4)
        self.assertAlmostEqual(s["win_rate_ci_lo"], lo)

    def test_summary_empty_and_single(self):
        s = m.summarize_simulated_trades([], [])
        self.assertEqual((s["n_trades"], s["net_pnl_usd"], s["max_drawdown_usd"]), (0, 0.0, 0.0))
        self.assertTrue(np.isnan(s["ev_per_contract_usd"]) and np.isnan(s["win_rate"]))
        s1 = m.summarize_simulated_trades([0.5], [1])
        self.assertTrue(np.isnan(s1["ev_se_usd"]))
        with self.assertRaises(ValueError):
            m.summarize_simulated_trades([0.5], [1, 0])

    def test_cluster_mean_ci_deterministic(self):
        a = m.cluster_mean_ci([1, 1, 3], ["x", "x", "y"], seed=1)
        self.assertEqual(a, m.cluster_mean_ci([1, 1, 3], ["x", "x", "y"], seed=1))
        self.assertAlmostEqual(a["mean"], 2.0)
        self.assertEqual(m.cluster_mean_ci([], [])["n_clusters"], 0)


if __name__ == "__main__":
    unittest.main()
