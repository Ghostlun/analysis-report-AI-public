import copy
import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import matplotlib.pyplot as plt  # noqa: E402

import generate_charts as gc  # noqa: E402
import generate_dashboards as gd  # noqa: E402
from shared.dashboard_schemas import DASHBOARDS, FORBIDDEN_VALUE_RE  # noqa: E402
from test_dashboards import GEN_AT, make_market_csv, make_sim_dir  # noqa: E402


class ChartBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        csv = cls.dir / "KXBTC15M_all.csv"
        make_market_csv(csv)
        sim = cls.dir / "sim"
        sim.mkdir()
        make_sim_dir(sim)
        cls.dash = cls.dir / "dash"
        gd.generate(cls.dash, csv, sim, GEN_AT)
        cls.docs = gc.load_dashboards(cls.dash)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def render(self, name, doc):
        """Render one chart, returning (svg path, figure texts, axes) captured before the figure is closed."""
        cap = {}
        orig = gc._save

        def spy(fig, path):
            cap["axes"] = list(fig.axes)
            cap["texts"] = [t.get_text() for t in fig.findobj(matplotlib_text)]
            cap["lines"] = [(l.get_xdata(), l.get_ydata()) for ax in fig.axes for l in ax.get_lines()]
            orig(fig, path)
        gc._save = spy
        try:
            p = self.dir / "out" / f"{name}.svg"
            gc.CHARTS[name](doc, p)
        finally:
            gc._save = orig
        return p, cap


import matplotlib.text as _mt  # noqa: E402

matplotlib_text = _mt.Text


class TestChartOutput(ChartBase):
    def test_all_svgs_valid_xml(self):
        paths = gc.generate(self.dash, self.dir / "svg")
        self.assertEqual(set(paths), set(DASHBOARDS))
        for p in paths.values():
            root = ET.parse(p).getroot()
            self.assertTrue(root.tag.endswith("svg"))
            self.assertGreater(p.stat().st_size, 5000)

    def test_reproducible_bytes(self):
        a = gc.generate(self.dash, self.dir / "r1")
        b = gc.generate(self.dash, self.dir / "r2")
        for n in DASHBOARDS:
            self.assertEqual(a[n].read_bytes(), b[n].read_bytes())

    def test_no_leftover_temp_files(self):
        gc.generate(self.dash, self.dir / "tmpchk")
        self.assertEqual(list((self.dir / "tmpchk").glob("*.tmp")), [])

    def test_no_sensitive_content_in_svg_or_text(self):
        paths = gc.generate(self.dash, self.dir / "sens")
        for n, p in paths.items():
            raw = p.read_text(encoding="utf-8")
            self.assertIsNone(FORBIDDEN_VALUE_RE.search(raw), n)
            self.assertNotIn("SYN-", raw)
        for n in DASHBOARDS:
            _, cap = self.render(n, self.docs[n])
            for t in cap["texts"]:
                self.assertIsNone(FORBIDDEN_VALUE_RE.search(t), t)
                self.assertFalse(re.search(r"order|balance|account|api", t, re.I), t)


class TestChartsUseJsonValues(ChartBase):
    def test_market_line_matches_json(self):
        doc = self.docs["market_overview"]
        _, cap = self.render("market_overview", doc)
        expected = np.array([np.nan if v is None else v for v in doc["reference_price_series"]["1h"]["close"]])
        y = cap["lines"][0][1]
        np.testing.assert_array_equal(np.isnan(y), np.isnan(expected))
        np.testing.assert_allclose(y[~np.isnan(y)], expected[~np.isnan(expected)])

    def test_technical_gaps_preserved_and_values_match(self):
        doc = self.docs["technical_indicators"]
        s = doc["intervals"]["1h"]["series"]
        _, cap = self.render("technical_indicators", doc)
        ys = [y for _, y in cap["lines"]]
        sma = next(y for y in ys if np.array_equal(np.isnan(y), np.isnan(np.array([np.nan if v is None else v for v in s["sma_20"]]))))
        exp = np.array([np.nan if v is None else v for v in s["sma_20"]])
        np.testing.assert_allclose(sma[~np.isnan(sma)], exp[~np.isnan(exp)])
        self.assertTrue(np.isnan(sma[:19]).all())  # warm-up is not drawn

    def test_prediction_values_match(self):
        doc = self.docs["prediction_analysis"]
        _, cap = self.render("prediction_analysis", doc)
        bins = sorted(doc["by_time_bin"], key=lambda b: b["seconds_lo"])
        acc = [b["results"]["logistic"]["accuracy"] for b in bins]
        self.assertTrue(any(np.allclose(y, acc) for _, y in cap["lines"]))
        joined = "\n".join(cap["texts"])
        self.assertIn(f"n={bins[0]['n_snapshots']:,}", joined)
        self.assertIn("Independent market counts: unavailable", joined)
        self.assertIn("No model superiority is claimed", joined)

    def test_strategy_values_and_no_best_label(self):
        doc = self.docs["strategy_research"]
        _, cap = self.render("strategy_research", doc)
        joined = "\n".join(cap["texts"]).lower()
        self.assertIn("simulated", joined)
        self.assertNotRegex(joined, r"\bbest\b(?! configuration is selected)")
        self.assertNotIn("live trading performance", joined)
        row = next(f for f in doc["families"] if f["family_id"] == "gap_rule" and f["scenario"] == "slip_0.01"
                   and f["period"] == "test")
        xs = [float(x) for xdata, _ in cap["lines"] for x in np.atleast_1d(xdata)]
        self.assertTrue(any(abs(x - row["ev_per_contract_usd"]["median"]) < 1e-9 for x in xs))
        # rows are alphabetical, never sorted by performance
        labels = [t for t in cap["texts"] if "cfgs=" in t]
        self.assertEqual(labels, sorted(labels))


class TestMissingDataAndValidation(ChartBase):
    def test_empty_inputs_render_without_error(self):
        docs = copy.deepcopy(self.docs)
        docs["prediction_analysis"]["by_time_bin"] = []
        docs["strategy_research"]["families"] = []
        for n in ("prediction_analysis", "strategy_research"):
            p, _ = self.render(n, docs[n])
            ET.parse(p)

    def test_unavailable_series_render(self):
        doc = copy.deepcopy(self.docs["market_overview"])
        doc["reference_price_summary"].update(status="unavailable")
        s = doc["reference_price_series"]["1h"]
        for k in s:
            s[k] = []
        p, cap = self.render("market_overview", doc)
        ET.parse(p)
        self.assertIn("BTC reference series unavailable", cap["texts"])
        t = copy.deepcopy(self.docs["technical_indicators"])
        t["intervals"]["1h"]["status"] = "unavailable"
        p, cap = self.render("technical_indicators", t)
        ET.parse(p)

    def test_all_nan_indicator_values(self):
        t = copy.deepcopy(self.docs["technical_indicators"])
        s = t["intervals"]["1h"]["series"]
        for k in ("sma_20", "ema_20", "rsi_14", "realized_vol_24_ann_pct"):
            s[k] = [None] * len(s[k])
        p, _ = self.render("technical_indicators", t)
        ET.parse(p)

    def test_invalid_schema_blocks_rendering(self):
        d = self.dir / "bad"
        d.mkdir(exist_ok=True)
        for n, doc in self.docs.items():
            (d / f"{n}.json").write_text(json.dumps(doc))
        bad = copy.deepcopy(self.docs["strategy_research"])
        bad["results_type"]["account_balance"] = 1
        (d / "strategy_research.json").write_text(json.dumps(bad))
        out = self.dir / "badout"
        with self.assertRaises(ValueError):
            gc.generate(d, out)
        self.assertFalse(out.exists())

    def test_missing_json_blocks_rendering(self):
        d = self.dir / "missing"
        d.mkdir(exist_ok=True)
        with self.assertRaises(FileNotFoundError):
            gc.generate(d, self.dir / "x")

    def test_non_finite_json_rejected(self):
        d = self.dir / "nan"
        d.mkdir(exist_ok=True)
        for n, doc in self.docs.items():
            (d / f"{n}.json").write_text(json.dumps(doc))
        txt = (d / "market_overview.json").read_text().replace('"mean":', '"mean":NaN,"x":', 1)
        (d / "market_overview.json").write_text(txt)
        with self.assertRaises(ValueError):
            gc.generate(d, self.dir / "nanout")

    def test_source_json_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.dash.glob("*.json")}
        gc.generate(self.dash, self.dir / "imm")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.dash.glob("*.json")})


class TestReadmeReferences(unittest.TestCase):
    def test_readme_references_chart_files(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for n in DASHBOARDS:
            self.assertIn(f"](assets/charts/{n}.svg)", readme)
            self.assertTrue((ROOT / "assets" / "charts" / f"{n}.svg").exists(), n)
        self.assertNotRegex(readme, r"!\[[^\]]*\]\((https?:|/|[A-Za-z]:)")
        self.assertIn("raw market data", readme)


if __name__ == "__main__":
    unittest.main()
