import copy
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from shared import dashboards as dash  # noqa: E402
from shared.dashboard_schemas import SCHEMAS, DASHBOARDS, safety_scan, validate, validate_dashboard  # noqa: E402
import generate_dashboards as gen  # noqa: E402

GEN_AT = "2026-01-01T00:00:00Z"


def make_market_csv(path: Path, with_gap=True):
    rng = np.random.default_rng(1)
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    price = 50000.0
    for i in range(0, 4 * 3600, 15):
        t = start + pd.Timedelta(seconds=i)
        price *= 1 + rng.normal(0, 0.0002)
        if with_gap and 100 * 60 <= i < 130 * 60:
            continue
        k = i // 900
        close = start + pd.Timedelta(minutes=15 * (k + 1))
        yes = 0.4 + 0.2 * ((k % 2) == 0)
        rows.append({
            "ticker": f"SYN-{k}", "collected_at_utc": t.isoformat(), "reference_timestamp": t.isoformat(),
            "reference_price_usd": price, "floor_strike": 50000.0, "close_time": close.isoformat(),
            "yes_bid_usd": yes - 0.02, "yes_ask_usd": yes + 0.02, "no_bid_usd": 1 - yes - 0.02,
            "no_ask_usd": 1 - yes + 0.02, "last_price_usd": yes, "volume_contracts": 100.0,
            "official_settlement_result": "yes" if k % 2 == 0 else "no", "settlement_status": "finalized",
            "settlement_timestamp": close.isoformat(),
        })
    pd.DataFrame(rows).to_csv(path, index=False)


def make_sim_dir(d: Path):
    bins = ["(30, 60]", "(60, 90]"]
    pd.DataFrame({"sec_bin": bins, "n": [100, 200], "brier_market": [0.05, 0.06], "acc_market": [0.9, 0.88],
                  "brier_logit": [0.051, 0.059], "acc_logit": [0.9, 0.89], "brier_gbm": [0.05, 0.06],
                  "acc_gbm": [0.9, 0.88], "brier_analog_knn": [0.07, 0.07], "acc_analog_knn": [0.85, 0.85]}
                 ).to_csv(d / "pattern_model_by_time.csv", index=False)
    pd.DataFrame({"model": ["logit", "gbm"], "margin": [0.02, 0.03], "window": ["30-120s", "30-180s"],
                  "n_dev": [10, 12], "ev_dev": [0.01, -0.02], "n_test": [20, 25], "wr_test": [0.5, 0.6],
                  "ev_test": [0.02, 0.01], "ev_test_se": [0.02, 0.02], "n_test_delay": [19, 24],
                  "ev_test_delay15s": [-0.01, 0.0]}).to_csv(d / "pattern_model_policy_grid.csv", index=False)
    pd.DataFrame({"model": ["logit", "logit"], "conf": [0.8, 0.85], "fill": ["immediate", "delay15s"],
                  "n_dev": [5, 6], "ev_dev": [0.0, 0.01], "n_test": [30, 31], "wr_test": [0.9, 0.91],
                  "avg_price_test": [0.9, 0.9], "ev_test": [0.0, 0.01], "ev_test_se": [0.02, 0.02]}
                 ).to_csv(d / "pattern_model_4min_gate.csv", index=False)
    pd.DataFrame({"target_wilson_lb": [0.9, 0.9], "fill": ["immediate", "immediate"], "period": ["dev", "test"],
                  "n": [50, 60], "wr": [0.9, 0.91], "avg_price": [0.89, 0.9], "ev_per_contract": [0.003, 0.0],
                  "se": [0.017, 0.013], "avg_sec": [200.0, 201.0]}).to_csv(d / "gap_rule_results.csv", index=False)
    pd.DataFrame({"mode": ["all", "std_only"], "zmin": [0.0, 1.5], "persist": [1, 1], "maxp": [0.97, 0.97],
                  "n": [100, 50], "wins": [90, 46], "net": [-10.0, -2.0], "net_lo": [-40.0, -20.0],
                  "maxdd": [30.0, 12.0]}).to_csv(d / "momentum_v2_dev_grid.csv", index=False)


class DashboardTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.csv = cls.dir / "KXBTC15M_all.csv"
        make_market_csv(cls.csv)
        cls.sim = cls.dir / "sim"
        cls.sim.mkdir()
        make_sim_dir(cls.sim)
        cls.src = dash.Sources(cls.csv, cls.sim)
        cls.docs = {n: dash.BUILDERS[n](cls.src, GEN_AT) for n in DASHBOARDS}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestSchemaAndAllowlist(DashboardTestBase):
    def test_all_documents_valid(self):
        for n, d in self.docs.items():
            validate_dashboard(n, d)
            self.assertEqual(validate(d, SCHEMAS[n]), [])

    def test_unexpected_key_rejected_at_any_depth(self):
        for n in DASHBOARDS:
            d = copy.deepcopy(self.docs[n])
            d["meta"]["extra"] = 1
            with self.assertRaises(ValueError):
                validate_dashboard(n, d)
            d = copy.deepcopy(self.docs[n])
            d["meta"]["data_status"]["order_id"] = "x"
            with self.assertRaises(ValueError):
                validate_dashboard(n, d)

    def test_missing_key_rejected(self):
        d = copy.deepcopy(self.docs["market_overview"])
        del d["contract_volume"]
        with self.assertRaises(ValueError):
            validate_dashboard("market_overview", d)

    def test_forbidden_content_rejected(self):
        d = copy.deepcopy(self.docs["prediction_analysis"])
        d["limitations"].append("see KXBTC15M-26OCT30 for details")
        with self.assertRaises(ValueError):
            validate_dashboard("prediction_analysis", d)
        self.assertTrue(safety_scan({"api_key": 1}))
        self.assertTrue(safety_scan({"a": r"C:\Users\x\live_orders.csv"}))

    def test_source_file_allowlist(self):
        d = copy.deepcopy(self.docs["market_overview"])
        d["meta"]["source_files"][0]["name"] = "live_orders_all.csv"
        with self.assertRaises(ValueError):
            validate_dashboard("market_overview", d)

    def test_documents_marked_private_pending_and_historical(self):
        for d in self.docs.values():
            self.assertFalse(d["meta"]["data_status"]["is_live"])
            self.assertTrue(d["meta"]["publication_status"]["approved_for_public_release"])
            self.assertEqual("public_portfolio_aggregate", d["meta"]["publication_status"]["status"])

    def test_no_ticker_strings_leak(self):
        text = json.dumps(self.docs)
        self.assertNotIn("SYN-", text)


class TestNumericValidity(DashboardTestBase):
    def test_non_finite_values_rejected(self):
        for bad in (float("nan"), float("inf"), -float("inf")):
            d = copy.deepcopy(self.docs["market_overview"])
            d["reference_price_summary"]["mean"] = bad
            with self.assertRaises(ValueError):
                validate_dashboard("market_overview", d)

    def test_serialisation_has_no_nan(self):
        for d in self.docs.values():
            text = gen.serialize(d)
            self.assertNotIn("NaN", text)
            self.assertNotIn("Infinity", text)

    def test_num_helper(self):
        self.assertIsNone(dash.num(float("nan")))
        self.assertIsNone(dash.num(float("inf")))
        self.assertIsNone(dash.num("x"))
        self.assertEqual(dash.num(1.23456789, 3), 1.235)

    def test_wrong_type_rejected(self):
        d = copy.deepcopy(self.docs["market_overview"])
        d["snapshot_counts"]["markets"] = "many"
        with self.assertRaises(ValueError):
            validate_dashboard("market_overview", d)
        d = copy.deepcopy(self.docs["market_overview"])
        d["snapshot_counts"]["markets"] = True
        with self.assertRaises(ValueError):
            validate_dashboard("market_overview", d)


class TestMarketOverview(DashboardTestBase):
    def test_counts_and_outcomes(self):
        m = self.docs["market_overview"]
        self.assertEqual(m["snapshot_counts"]["markets"], 15)  # market 7 falls entirely inside the collection gap
        s = m["settlement_outcomes"]
        self.assertEqual(s["settled_yes"] + s["settled_no"] + s["unsettled_or_unknown"], s["markets"])
        self.assertEqual(s["settled_yes"], 8)

    def test_volume_unavailable_and_distinguished(self):
        m = self.docs["market_overview"]
        self.assertEqual(m["contract_volume"]["status"], "unavailable")
        self.assertEqual(m["btc_spot_volume"]["status"], "unavailable")
        self.assertIn("not a Kalshi contract price", m["definitions"]["btc_reference_price"])

    def test_series_does_not_forward_fill_gap(self):
        s = self.docs["market_overview"]["reference_price_series"]["15m"]
        self.assertIn(None, s["close"])
        for c, n in zip(s["close"], s["n_obs"]):
            if n == 0:
                self.assertIsNone(c)

    def test_gap_reported(self):
        self.assertGreaterEqual(self.docs["market_overview"]["reference_coverage"]["collection_gap_count"], 1)


class TestTechnicalIndicators(DashboardTestBase):
    def test_atr_vwap_volume_unavailable(self):
        st = self.docs["technical_indicators"]["indicator_status"]
        for k in ("atr", "vwap", "volume_indicators"):
            self.assertEqual(st[k]["status"], "unavailable")
            self.assertTrue(st[k]["reason"])
        for b in self.docs["technical_indicators"]["intervals"].values():
            self.assertFalse(any("atr" in k or "vwap" in k for k in b["series"]))

    def test_all_intervals_present_and_aligned(self):
        for iv, b in self.docs["technical_indicators"]["intervals"].items():
            n = b["coverage"]["bars_total"]
            for col, arr in b["series"].items():
                self.assertEqual(len(arr), n, f"{iv}.{col}")

    def test_warmup_and_incomplete_bar_masking(self):
        b = self.docs["technical_indicators"]["intervals"]["5m"]
        s = b["series"]
        first_valid = next(i for i, v in enumerate(s["sma_20"]) if v is not None)
        self.assertTrue(all(v is None for v in s["sma_20"][:first_valid]))
        self.assertGreaterEqual(first_valid, 19)
        # indicators are never present on a bar overlapping a collection gap
        for i, gap in enumerate(s["gap_affected"]):
            if gap:
                for k in ("sma_20", "ema_20", "rsi_14", "roc_12_pct", "realized_vol_24_bar_pct"):
                    self.assertIsNone(s[k][i], f"{k}@{i}")

    def test_partial_bars_masked(self):
        for b in self.docs["technical_indicators"]["intervals"].values():
            s = b["series"]
            for i, p in enumerate(s["partial"]):
                if p:
                    self.assertIsNone(s["sma_20"][i])

    def test_rsi_bounds_and_vol_nonnegative(self):
        s = self.docs["technical_indicators"]["intervals"]["1m"]["series"]
        for v in s["rsi_14"]:
            if v is not None:
                self.assertTrue(0 <= v <= 100)
        for v in s["realized_vol_24_bar_pct"]:
            if v is not None:
                self.assertGreaterEqual(v, 0)

    def test_volatility_definition_documented(self):
        v = self.docs["technical_indicators"]["parameters"]["volatility"]
        self.assertIn("RMS", v["estimator"])
        self.assertIn("percent", v["unit_bar"])

    def test_empty_reference_data_is_unavailable_not_fabricated(self):
        p = self.dir / "emptyref" / "KXBTC15M_all.csv"
        p.parent.mkdir(exist_ok=True)
        df = pd.read_csv(self.csv)
        df["reference_price_usd"] = np.nan
        df.to_csv(p, index=False)
        src = dash.Sources(p, self.sim)
        t = dash.build_technical_indicators(src, GEN_AT)
        validate_dashboard("technical_indicators", t)
        for b in t["intervals"].values():
            self.assertEqual(b["status"], "unavailable")
            self.assertEqual(b["coverage"]["bars_total"], 0)
        m = dash.build_market_overview(src, GEN_AT)
        validate_dashboard("market_overview", m)
        self.assertEqual(m["reference_price_summary"]["status"], "unavailable")
        self.assertIsNone(m["reference_price_summary"]["mean"])


class TestPredictionAnalysis(DashboardTestBase):
    def test_aggregates(self):
        p = self.docs["prediction_analysis"]
        self.assertEqual(p["snapshot_weighted_overall"]["n_snapshots"], 300)
        self.assertEqual(len(p["by_time_bin"]), 2)
        b = p["by_time_bin"][0]
        self.assertEqual(b["results"]["market_baseline"]["brier"], 0.05)
        self.assertAlmostEqual(b["results"]["logistic"]["brier_skill_vs_market"], 1 - 0.051 / 0.05, places=6)
        self.assertAlmostEqual(p["snapshot_weighted_overall"]["market_baseline"]["brier"], (0.05 * 100 + 0.06 * 200) / 300, places=6)

    def test_unavailable_states_and_no_superiority(self):
        p = self.docs["prediction_analysis"]
        self.assertEqual(p["calibration"]["status"], "unavailable")
        self.assertEqual(p["evaluation"]["n_test_markets"]["status"], "unavailable")
        self.assertIsNone(p["meta"]["sample_counts"]["test_markets"])
        self.assertEqual(p["comparison"]["superiority_claim"], "none")
        self.assertFalse(p["evaluation"]["all_market_exported_models_used"])
        for b in p["by_time_bin"]:
            self.assertEqual(b["n_markets"], {"status": "unavailable", "value": None})
        self.assertEqual(p["comparison"]["time_bins_model_brier_below_market"]["logistic"], 1)

    def test_missing_columns_fail(self):
        d = self.dir / "sim2"
        d.mkdir(exist_ok=True)
        make_sim_dir(d)
        df = pd.read_csv(d / "pattern_model_by_time.csv").drop(columns=["brier_gbm"])
        df.to_csv(d / "pattern_model_by_time.csv", index=False)
        with self.assertRaises(dash.MissingInputError):
            dash.build_prediction_analysis(dash.Sources(self.csv, d), GEN_AT)

    def test_missing_file_fails(self):
        d = self.dir / "sim3"
        d.mkdir(exist_ok=True)
        with self.assertRaises(dash.MissingInputError):
            dash.build_prediction_analysis(dash.Sources(self.csv, d), GEN_AT)


class TestStrategyResearch(DashboardTestBase):
    def test_simulated_only(self):
        s = self.docs["strategy_research"]
        self.assertEqual(s["results_type"]["kind"], "simulated")
        self.assertFalse(s["results_type"]["live_trading_data_included"])
        text = json.dumps(s).lower()
        self.assertEqual(safety_scan(s), [])
        for banned in ("live_orders", "order_id", "zmin", "maxp", "coefficient"):
            self.assertNotIn(banned, text)

    def test_assumptions_and_no_best_pick(self):
        s = self.docs["strategy_research"]
        self.assertEqual(s["assumptions"]["fee_rate"], 0.07)
        self.assertEqual(s["assumptions"]["slippage_usd"], 0.01)
        self.assertNotIn("best", [k.lower() for k in s])
        self.assertEqual(s["equity_curve"]["status"], "unavailable")

    def test_momentum_ev_and_drawdown(self):
        fam = [f for f in self.docs["strategy_research"]["families"] if f["family_id"] == "momentum_filter"]
        self.assertEqual(len(fam), 1)
        f = fam[0]
        self.assertEqual(f["period"], "dev")
        self.assertEqual(f["n_configurations"], 2)
        self.assertEqual(f["max_drawdown_usd_simulated"]["max"], 30.0)
        self.assertAlmostEqual(f["ev_per_contract_usd"]["min"], -10 / 500, places=6)

    def test_unavailable_win_rate_is_null_not_zero(self):
        f = next(f for f in self.docs["strategy_research"]["families"]
                 if f["family_id"] == "pattern_model_entry_policy" and f["scenario"] == "delay_15s")
        self.assertEqual(f["win_rate"]["n_valid"], 0)
        self.assertIsNone(f["win_rate"]["median"])


class TestGeneratorBehaviour(DashboardTestBase):
    def run_gen(self, out, at=GEN_AT, csv=None, sim=None):
        return gen.generate(out, csv or self.csv, sim or self.sim, at)

    def strip(self, p):
        d = json.loads(Path(p).read_text())
        d["meta"]["generated_at"] = None
        return d

    def test_deterministic_content(self):
        a, b = self.dir / "a", self.dir / "b"
        pa = self.run_gen(a, "2026-01-01T00:00:00Z")
        pb = self.run_gen(b, "2027-02-02T00:00:00Z")
        for n in DASHBOARDS:
            self.assertEqual(self.strip(pa[n]), self.strip(pb[n]))
        pc = self.run_gen(self.dir / "c", GEN_AT)
        for n in DASHBOARDS:
            self.assertEqual(Path(pa[n]).read_bytes(), Path(pc[n]).read_bytes())

    def test_source_data_immutable(self):
        import hashlib

        def h(p):
            return hashlib.sha256(Path(p).read_bytes()).hexdigest()
        files = [self.csv] + sorted(self.sim.glob("*.csv"))
        before = [h(f) for f in files]
        self.run_gen(self.dir / "imm")
        self.assertEqual(before, [h(f) for f in files])

    def test_failure_does_not_overwrite_existing_outputs(self):
        out = self.dir / "keep"
        self.run_gen(out)
        before = {p.name: p.read_bytes() for p in out.glob("*.json")}
        bad = self.dir / "sim_bad"
        bad.mkdir(exist_ok=True)
        make_sim_dir(bad)
        (bad / "gap_rule_results.csv").unlink()
        with self.assertRaises(dash.MissingInputError):
            self.run_gen(out, sim=bad)
        self.assertEqual(before, {p.name: p.read_bytes() for p in out.glob("*.json")})
        self.assertEqual(list(out.glob("*.tmp")), [])

    def test_validation_failure_blocks_all_writes(self):
        out = self.dir / "novalid"
        orig = gen.validate_dashboard

        def boom(name, doc):
            if name == "strategy_research":
                raise ValueError("forced")
            return orig(name, doc)
        gen.validate_dashboard = boom
        try:
            with self.assertRaises(ValueError):
                self.run_gen(out)
        finally:
            gen.validate_dashboard = orig
        self.assertFalse(out.exists() and any(out.iterdir()))

    def test_refuses_live_order_input(self):
        p = self.dir / "live_orders_all.csv"
        p.write_text("a,b\n1,2\n")
        with self.assertRaises(Exception):
            dash.Sources(p, self.sim)

    def test_generated_files_valid_json(self):
        paths = self.run_gen(self.dir / "valid")
        for n, p in paths.items():
            doc = json.loads(Path(p).read_text(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
            validate_dashboard(n, doc)
            self.assertTrue(doc["meta"]["generated_at"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
