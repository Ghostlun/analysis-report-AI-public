"""Render research charts (SVG) from the four validated dashboard JSON files only.

Usage:
    python scripts/generate_charts.py [--dashboards public/dashboards] [--out assets/charts]

Inputs are limited to ``public/dashboards/*.json``; each is validated against its schema/allowlist before rendering.
No raw datasets, live orders or account data are read. Output is deterministic (fixed SVG hash salt, no timestamps).
The charts are PRIVATE until licensing and security approval is granted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from shared.dashboard_schemas import DASHBOARDS, validate_dashboard  # noqa: E402

DEFAULT_IN = ROOT / "public" / "dashboards"
DEFAULT_OUT = ROOT / "assets" / "charts"

BG, PANEL, FG, MUTED, GRID = "#0d1117", "#161b22", "#e6edf3", "#8b949e", "#30363d"
C = {"price": "#58a6ff", "sma": "#f2cc60", "ema": "#ff7b72", "rsi": "#bc8cff", "vol": "#3fb950",
     "market_baseline": "#8b949e", "logistic": "#58a6ff", "gradient_boosting": "#f2cc60", "knn_analog": "#ff7b72",
     "neutral": "#58a6ff", "alt": "#d29922"}
MODEL_LABEL = {"market_baseline": "Market baseline", "logistic": "Logistic regression",
               "gradient_boosting": "Gradient boosting", "knn_analog": "kNN analog"}
FOOTER = "PRIVATE research snapshot - pending licensing & security approval - historical, not live - not investment advice"

plt.rcParams.update({
    "svg.hashsalt": "ai-datasets-charts", "svg.fonttype": "path", "font.family": "DejaVu Sans",
    "figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": GRID, "axes.labelcolor": FG,
    "text.color": FG, "xtick.color": MUTED, "ytick.color": MUTED, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.grid": True, "axes.titlesize": 11, "axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "legend.fontsize": 8, "legend.facecolor": PANEL, "legend.edgecolor": GRID, "axes.spines.top": False,
    "axes.spines.right": False,
})


def load_dashboards(directory: Path) -> dict[str, dict]:
    docs = {}
    for name in DASHBOARDS:
        p = Path(directory) / f"{name}.json"
        if not p.exists():
            raise FileNotFoundError(f"missing dashboard JSON: {p.name}")
        doc = json.loads(p.read_text(encoding="utf-8"),
                         parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"non-finite {c}")))
        validate_dashboard(name, doc)
        docs[name] = doc
    return docs


# ----------------------------------------------------------------------------- helpers
def _times(strings) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(strings), utc=True))


def _nan(values) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def _header(fig, title, subtitle):
    fig.text(0.02, 0.975, title, fontsize=15, fontweight="bold", va="top", ha="left")
    fig.text(0.02, 0.935, subtitle, fontsize=9, color=MUTED, va="top", ha="left")
    fig.text(0.02, 0.012, FOOTER, fontsize=7, color=MUTED, ha="left", va="bottom")


def _date_axis(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d", tz="UTC"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz="UTC"))


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        fig.savefig(tmp, format="svg", facecolor=BG, metadata={"Date": None, "Creator": "generate_charts.py"})
        os.replace(tmp, path)
    finally:
        plt.close(fig)
        if os.path.exists(tmp):
            os.unlink(tmp)


def _note(ax, text, loc=(0.01, 0.97), **kw):
    ax.text(*loc, text, transform=ax.transAxes, fontsize=7.5, color=MUTED, va="top", ha="left", **kw)


def _unavailable(ax, msg):
    ax.text(0.5, 0.5, msg, transform=ax.transAxes, ha="center", va="center", color=MUTED, fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])


# ----------------------------------------------------------------------------- charts
def chart_market_overview(doc: dict, path: Path):
    s = doc["reference_price_series"]["1h"]
    ps, cov, cnt = doc["reference_price_summary"], doc["reference_coverage"], doc["snapshot_counts"]
    fig = plt.figure(figsize=(11, 7.2))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1.4], left=0.08, right=0.97, top=0.86, bottom=0.2, hspace=0.45)
    _header(fig, "Market Overview - BTC reference index",
            f"Hourly bars, UTC | {ps['first_time']} to {ps['last_time']} | BTC reference index level, "
            "not a Kalshi contract price")
    ax = fig.add_subplot(gs[0])
    if ps["status"] != "available" or not s["time"]:
        _unavailable(ax, "BTC reference series unavailable")
    else:
        t, y = _times(s["time"]), _nan(s["close"])
        ax.plot(t, y, color=C["price"], lw=1.2, label="Reference index (last obs. per hour)")
        missing = np.isnan(y)
        ax.fill_between(t, 0, 1, where=missing, transform=ax.get_xaxis_transform(), color=C["alt"], alpha=0.25, lw=0,
                        label="No data (collection gap)")
        ax.set_ylabel("BTC reference index (USD per BTC)")
        ax.set_xlabel("Time (UTC)")
        ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
        _date_axis(ax)
        ax.legend(loc="upper right")
        _note(ax,         f"Range \\${ps['min']:,.0f}-\\${ps['max']:,.0f} | first \\${ps['first_value']:,.0f} to last "
                          f"\\${ps['last_value']:,.0f} ({ps['change_pct_first_to_last']:+.2f}%) | gaps are not filled",
              (0.01, 0.12))
    ax.set_title("Historical BTC reference index (USD)", loc="left")

    ax2 = fig.add_subplot(gs[1])
    if s["time"]:
        df = pd.DataFrame({"t": _times(s["time"]), "has": ~np.isnan(_nan(s["close"]))})
        daily = df.groupby(df["t"].dt.strftime("%Y-%m-%d"))["has"].sum()
        ax2.bar(range(len(daily)), daily.to_numpy(), color=C["neutral"], width=0.8)
        ax2.set_xticks(range(len(daily)))
        ax2.set_xticklabels([d[5:] for d in daily.index], rotation=90)
        ax2.set_ylim(0, 24)
        ax2.set_ylabel("Hourly bars with data")
        ax2.set_xlabel("Day (UTC); full day = 24 bars")
    else:
        _unavailable(ax2, "coverage unavailable")
    ax2.set_title("Data collection coverage", loc="left")
    fig.text(0.02, 0.05,
             f"{cnt['snapshot_rows']:,} snapshot rows | {cnt['markets']:,} markets | "
             f"{ps['n_observations']:,} unique reference observations | {cov['collection_gap_count']} gaps > "
             f"{cov['collection_gap_min_seconds']:.0f}s | {cov['share_rows_without_reference']:.1%} rows lack a reference",
             fontsize=7.5, color=FG, ha="left", va="bottom")
    _save(fig, path)


def chart_technical_indicators(doc: dict, path: Path):
    blk = doc["intervals"]["1h"]
    s, cov = blk["series"], blk["coverage"]
    fig = plt.figure(figsize=(11, 9))
    gs = fig.add_gridspec(3, 1, height_ratios=[3, 1.5, 1.5], left=0.08, right=0.97, top=0.88, bottom=0.09, hspace=0.32)
    p = doc["parameters"]
    _header(fig, "Technical Indicators - BTC reference index",
            f"1-hour bars, UTC | SMA{p['sma_window_bars']}, EMA{p['ema_window_bars']}, RSI{p['rsi_window_bars']} (Wilder), "
            f"realized vol over {p['realized_vol_window_bars']} bars | close-only levels, no OHLC/volume")
    if blk["status"] != "available":
        ax = fig.add_subplot(gs[:])
        _unavailable(ax, "Indicators unavailable")
        _save(fig, path)
        return
    t = _times(s["time"])
    axes = [fig.add_subplot(gs[i]) for i in range(3)]
    a1, a2, a3 = axes
    a1.plot(t, _nan(s["close"]), color=C["price"], lw=1.0, label="Close")
    a1.plot(t, _nan(s["sma_20"]), color=C["sma"], lw=1.2, label=f"SMA {p['sma_window_bars']}")
    a1.plot(t, _nan(s["ema_20"]), color=C["ema"], lw=1.2, label=f"EMA {p['ema_window_bars']}")
    a1.set_ylabel("USD per BTC")
    a1.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
    a1.set_title("Reference index with moving averages", loc="left")
    a1.legend(loc="upper right", ncol=3)
    a2.plot(t, _nan(s["rsi_14"]), color=C["rsi"], lw=1.0)
    for lvl in (30, 70):
        a2.axhline(lvl, color=MUTED, lw=0.7, ls="--")
    a2.set_ylim(0, 100)
    a2.set_ylabel("RSI (0-100)")
    a2.set_title("RSI (Wilder smoothing)", loc="left")
    a3.plot(t, _nan(s["realized_vol_24_ann_pct"]), color=C["vol"], lw=1.0)
    a3.set_ylabel("Annualized vol (% per year)")
    a3.set_title("Realized volatility (RMS of log returns; annualized, 24/7, independence assumed)", loc="left")
    a3.set_xlabel("Time (UTC)")
    for ax in axes:
        _date_axis(ax)
        for gap in (np.isnan(_nan(s["close"])),):
            ax.fill_between(t, 0, 1, where=gap, transform=ax.get_xaxis_transform(), color=C["alt"], alpha=0.2, lw=0)
    for ax in (a1, a2):
        ax.tick_params(labelbottom=False)
    v = blk["valid_indicator_values"]
    _note(a1, f"Shaded = missing bars (not filled) | {cov['bars_with_data']} of {cov['bars_total']} bars have data | "
              f"{cov['partial_bars']} partial, {cov['gap_affected_bars']} gap-affected bars excluded from indicator inputs",
          (0.01, 0.1))
    _note(a3, f"Valid values: RSI {v['rsi_14']}, SMA {v['sma_20']}, vol {v['realized_vol_24_ann_pct']} of {cov['bars_total']} "
              "bars. Annualized vol is noisy on a ~12-day sample. ATR/VWAP unavailable (no OHLC/volume).", (0.01, 0.95))
    _save(fig, path)


def chart_prediction_analysis(doc: dict, path: Path):
    bins = sorted(doc["by_time_bin"], key=lambda b: b["seconds_lo"])
    ev = doc["evaluation"]
    fig = plt.figure(figsize=(11, 7.8))
    gs = fig.add_gridspec(2, 1, left=0.08, right=0.97, top=0.86, bottom=0.27, hspace=0.55)
    _header(fig, "Prediction Analysis - model vs market baseline",
            f"Out-of-sample test snapshots {ev['test_period_start'][:10]} to {(ev['test_period_end'] or '')[:10]} (UTC) | "
            "models fit on development markets only")
    ids = ["market_baseline", "logistic", "gradient_boosting", "knn_analog"]
    labels = [f"{b['time_bin']}\nn={b['n_snapshots']:,}" for b in bins]
    x = np.arange(len(bins))
    ax1, ax2 = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    if not bins:
        _unavailable(ax1, "No prediction results available")
        _unavailable(ax2, "")
        _save(fig, path)
        return
    for i, m in enumerate(ids):
        acc = _nan([b["results"][m]["accuracy"] for b in bins])
        ax1.plot(x, acc, marker="o", ms=4, lw=1.3, color=C[m], label=MODEL_LABEL[m])
    ax1.set_ylabel("Directional accuracy (0.5 threshold)")
    ax1.set_title("Accuracy by time remaining to close", loc="left")
    ax1.legend(loc="lower right", ncol=4)
    w = 0.2
    for i, m in enumerate(ids):
        br = _nan([b["results"][m]["brier"] for b in bins])
        ax2.bar(x + (i - 1.5) * w, br, w, color=C[m], label=MODEL_LABEL[m])
    ax2.set_ylabel("Brier score (lower is better)")
    ax2.set_title("Brier score by time remaining to close", loc="left")
    for ax in (ax1, ax2):
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_xlabel("Seconds to close (bin) | n = snapshots")
    ov, cmp_ = doc["snapshot_weighted_overall"], doc["comparison"]
    below = cmp_["time_bins_model_brier_below_market"]
    fig.text(0.02, 0.135,
             f"Sample sizes are SNAPSHOT counts ({ov['n_snapshots']:,} total); snapshots within a market are correlated. "
             "Independent market counts: unavailable.", fontsize=8, color=FG)
    fig.text(0.02, 0.105,
             f"Bins where model Brier < market baseline (of {cmp_['time_bins_total']}): logistic {below['logistic']}, "
             f"gradient boosting {below['gradient_boosting']}, kNN {below['knn_analog']}. Max |difference| "
             f"{cmp_['max_abs_brier_difference_vs_market']:.4f}.", fontsize=8, color=FG)
    fig.text(0.02, 0.075, "No model superiority is claimed: no significance test or market-level clustering is possible; "
                          "calibration unavailable (no per-prediction records).", fontsize=8, color=MUTED)
    _save(fig, path)


FAMILY_SHORT = {"pattern_model_entry_policy": "Entry policy", "pattern_model_four_minute_gate": "4-min gate",
                "gap_rule": "Gap rule"}


def _strategy_rows(doc, scenario, period="test"):
    rows = {}
    for f in doc["families"]:
        if f["scenario"] == scenario and f["period"] == period and f["family_id"] in FAMILY_SHORT:
            name = FAMILY_SHORT[f["family_id"]] + (f" / {MODEL_LABEL.get(f['model'], f['model'])}" if f["model"] else "")
            rows[name] = f
    return dict(sorted(rows.items()))  # alphabetical: no ranking by performance


def chart_strategy_research(doc: dict, path: Path):
    slip = _strategy_rows(doc, "slip_0.01")
    delay = _strategy_rows(doc, "delay_15s")
    a = doc["assumptions"]
    fig = plt.figure(figsize=(11, 9.2))
    gs = fig.add_gridspec(2, 2, left=0.27, right=0.97, top=0.87, bottom=0.17, hspace=0.45, wspace=0.12)
    _header(fig, "Strategy Research - SIMULATED backtests only",
            f"Test period; fee rate {a['fee_rate']}, slippage \\${a['slippage_usd']:.2f}; bars = median across simulated "
            "configurations, whiskers = min-max | no live trading data")
    names = list(slip)
    y = np.arange(len(names))
    axw = fig.add_subplot(gs[0, 0])
    axe = fig.add_subplot(gs[0, 1], sharey=axw)
    axs = fig.add_subplot(gs[1, :])
    if not names:
        for ax in (axw, axe, axs):
            _unavailable(ax, "No simulated results available")
        _save(fig, path)
        return

    def ranged(ax, key, scale=1.0):
        for i, n in enumerate(names):
            st = slip[n][key]
            if st["n_valid"] == 0:
                ax.text(0.02, i, "n/a", va="center", color=MUTED, fontsize=8, transform=ax.get_yaxis_transform())
                continue
            ax.errorbar(st["median"] * scale, i, xerr=[[(st["median"] - st["min"]) * scale], [(st["max"] - st["median"]) * scale]],
                        fmt="o", color=C["neutral"], ecolor=MUTED, capsize=3, ms=5)

    ranged(axw, "win_rate", 100)
    axw.set_yticks(y)
    axw.set_yticklabels([f"{n}  (cfgs={slip[n]['n_configurations']})" for n in names], fontsize=7.5)
    axw.invert_yaxis()
    axw.set_xlabel("Win rate (%)")
    axw.set_title("Win rate", loc="left")
    ranged(axe, "ev_per_contract_usd")
    axe.axvline(0, color=MUTED, lw=0.8)
    axe.tick_params(labelleft=False)
    axe.set_xlabel("Expected value (USD per contract, after fees)")
    axe.set_title("Expected value", loc="left")

    shared = [n for n in names if n in delay and delay[n]["ev_per_contract_usd"]["n_valid"]]
    h = 0.38
    ys = np.arange(len(shared))
    for off, lab, sc, col in ((-h / 2, "Immediate fill (+\\$0.01 slippage)", slip, C["neutral"]),
                              (h / 2, "Delayed fill (15 s)", delay, C["alt"])):
        med = [sc[n]["ev_per_contract_usd"]["median"] for n in shared]
        bars = axs.barh(ys + off, med, h, color=col, label=lab)
        axs.bar_label(bars, labels=[f"{m:+.3f}" for m in med], fontsize=7, color=MUTED, padding=2)
    axs.set_yticks(ys)
    axs.set_yticklabels(shared, fontsize=7.5)
    axs.invert_yaxis()
    axs.axvline(0, color=MUTED, lw=0.8)
    axs.set_xlabel("Median expected value (USD per contract)")
    axs.set_title("Fill-delay sensitivity (test period)", loc="left")
    axs.legend(loc="lower right")
    fig.text(0.02, 0.105, "Configurations on the same test set were compared, so ranges are not unbiased performance "
                          "estimates; no best configuration is selected. Trades per configuration are correlated.",
             fontsize=8, color=FG)
    fig.text(0.02, 0.075, "Momentum-filter family has development-period results only and is omitted here. Strategy "
                          "parameters are withheld. Results do not show consistent profitability.", fontsize=8, color=MUTED)
    _save(fig, path)


CHARTS = {
    "market_overview": chart_market_overview,
    "technical_indicators": chart_technical_indicators,
    "prediction_analysis": chart_prediction_analysis,
    "strategy_research": chart_strategy_research,
}


def generate(dashboards_dir: Path = DEFAULT_IN, out_dir: Path = DEFAULT_OUT) -> dict[str, Path]:
    docs = load_dashboards(dashboards_dir)  # validate everything before rendering anything
    out = {}
    for name, fn in CHARTS.items():
        p = Path(out_dir) / f"{name}.svg"
        fn(docs[name], p)
        out[name] = p
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dashboards", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    try:
        paths = generate(a.dashboards, a.out)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for n, p in paths.items():
        print(f"{n}: {p} ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
