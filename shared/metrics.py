"""Statistical metrics for prediction and simulated-strategy evaluation.

Counting rule: ``n_snapshots`` (rows) and ``n_markets`` (unique market ids) are always reported separately. Snapshots
from one market are strongly correlated, so intervals/means that claim to be market-level use one value per market.

Everything about trades here is SIMULATED. No function accepts or returns live-order data, and results carry
``"source": "simulated"`` together with the fee/slippage assumptions that produced them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

KALSHI_FEE_RATE = 0.07          # same value as src/momentum.py::FEE_RATE
MAX_EXEC_PRICE = 0.99           # same cap as src/momentum.py::replay and src/kalshi_lib.py::CAP
NAN = float("nan")


def _paired(p, y):
    p = np.asarray(p, dtype="float64").ravel()
    y = np.asarray(y, dtype="float64").ravel()
    if p.shape != y.shape:
        raise ValueError("predictions and outcomes must have the same length")
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    if len(p) and ((p < 0) | (p > 1)).any():
        raise ValueError("probabilities must lie in [0, 1]")
    if len(y) and not np.isin(y, (0.0, 1.0)).all():
        raise ValueError("outcomes must be 0 or 1")
    return p, y, ok


def directional_accuracy(p, y, threshold: float = 0.5) -> float:
    """Share of cases where ``(p >= threshold) == y``. NaN pairs are dropped; empty input gives NaN."""
    p, y, _ = _paired(p, y)
    return float(np.mean((p >= threshold) == (y == 1.0))) if len(p) else NAN


def brier_score(p, y) -> float:
    """Mean squared error of probability forecasts, ``mean((p - y)^2)``; 0 is perfect, 0.25 is a constant 0.5 forecast."""
    p, y, _ = _paired(p, y)
    return float(np.mean((p - y) ** 2)) if len(p) else NAN


def brier_skill_score(p_model, p_baseline, y) -> float:
    """``1 - Brier(model) / Brier(baseline)`` on rows where all three are valid. Negative = worse than baseline.

    NaN when there are no valid rows or the baseline Brier is 0.
    """
    pm = np.asarray(p_model, dtype="float64").ravel()
    pb = np.asarray(p_baseline, dtype="float64").ravel()
    yy = np.asarray(y, dtype="float64").ravel()
    if not (pm.shape == pb.shape == yy.shape):
        raise ValueError("inputs must have the same length")
    ok = np.isfinite(pm) & np.isfinite(pb) & np.isfinite(yy)
    if not ok.any():
        return NAN
    b_base = brier_score(pb[ok], yy[ok])
    if b_base == 0:
        return NAN
    return float(1.0 - brier_score(pm[ok], yy[ok]) / b_base)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, bounded to [0, 1]; (NaN, NaN) when ``n == 0``.

    Numerically identical to ``src/momentum.py::wilson`` (checked in tests) plus input validation and clipping.
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError("require 0 <= k <= n")
    if n == 0:
        return (NAN, NAN)
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (float(max(0.0, (centre - half) / den)), float(min(1.0, (centre + half) / den)))


def win_rate(wins: int, n: int, z: float = 1.96) -> dict:
    lo, hi = wilson_interval(int(wins), int(n), z)
    return {"n": int(n), "wins": int(wins), "win_rate": (wins / n) if n else NAN, "ci_lo": lo, "ci_hi": hi}


def sample_counts(df: pd.DataFrame, market_col: str | None = "ticker") -> dict:
    """``n_snapshots`` = rows; ``n_markets`` = unique non-null market ids (None if the column is absent)."""
    n_markets = int(df[market_col].nunique()) if market_col and market_col in df.columns else None
    return {"n_snapshots": int(len(df)), "n_markets": n_markets}


def cluster_mean_ci(values, groups, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05) -> dict:
    """Market-level mean: average within each group first, then across groups; cluster bootstrap CI over groups.

    Deterministic for a given ``seed``. Rows with NaN value/group are dropped. Empty input gives NaN fields.
    """
    s = pd.DataFrame({"v": np.asarray(values, dtype="float64"), "g": pd.Series(groups).to_numpy()}).dropna()
    if s.empty:
        return {"n_rows": 0, "n_clusters": 0, "mean": NAN, "ci_lo": NAN, "ci_hi": NAN}
    per = s.groupby("g", sort=True)["v"].mean().to_numpy()
    rng = np.random.default_rng(seed)
    boots = rng.choice(per, (n_boot, len(per))).mean(axis=1)
    return {"n_rows": int(len(s)), "n_clusters": int(len(per)), "mean": float(per.mean()),
            "ci_lo": float(np.quantile(boots, alpha / 2)), "ci_hi": float(np.quantile(boots, 1 - alpha / 2))}


def evaluate_predictions(df: pd.DataFrame, p_col: str, y_col: str, baseline_col: str | None = None,
                         market_col: str | None = "ticker", threshold: float = 0.5, seed: int = 0) -> dict:
    """Prediction summary with snapshot-level and market-level views.

    Snapshot-level numbers pool correlated rows; ``market_level`` gives the Brier score as the equal-weight mean over
    markets with a cluster-bootstrap interval. ``market_level`` is None when no market identifier exists.
    Only valid (finite) prediction/outcome pairs are counted.
    """
    cols = [c for c in (p_col, y_col, baseline_col, market_col) if c and c in df.columns]
    d = df[cols].copy()
    valid = d[p_col].notna() & d[y_col].notna()
    if baseline_col:
        valid &= d[baseline_col].notna()
    d = d[valid]
    out = {
        "counts": sample_counts(d, market_col),
        "accuracy": directional_accuracy(d[p_col], d[y_col], threshold),
        "brier": brier_score(d[p_col], d[y_col]),
        "baseline_brier": brier_score(d[baseline_col], d[y_col]) if baseline_col else None,
        "brier_skill_vs_baseline": brier_skill_score(d[p_col], d[baseline_col], d[y_col]) if baseline_col else None,
        "market_level": None,
    }
    if market_col and market_col in d.columns:
        out["market_level"] = cluster_mean_ci((d[p_col].to_numpy() - d[y_col].to_numpy()) ** 2, d[market_col], seed=seed)
    return out


@dataclass(frozen=True)
class TradeAssumptions:
    """Assumptions behind simulated trade results; stored with every result."""
    contracts_per_trade: int = 5
    slippage_usd: float = 0.01
    fee_rate: float = KALSHI_FEE_RATE
    max_price: float = MAX_EXEC_PRICE
    fill_delay_s: float = 0.0

    def __post_init__(self):
        if self.contracts_per_trade <= 0:
            raise ValueError("contracts_per_trade must be positive")
        if self.slippage_usd < 0 or self.fee_rate < 0:
            raise ValueError("slippage and fee rate must be non-negative")
        if not 0 < self.max_price <= 1:
            raise ValueError("max_price must be in (0, 1]")


def kalshi_taker_fee(price, contracts=1, fee_rate: float = KALSHI_FEE_RATE):
    """Unrounded taker fee ``fee_rate * n * p * (1 - p)`` in USD (matches ``src/momentum.py::fee``).

    The exact exchange fee is rounded up to a cent grid by ``src/kalshi_lib.py::fee``; this unrounded form is the one
    used by the existing simulations.
    """
    return fee_rate * contracts * price * (1 - price)


def simulate_trade_pnl(entry_price, won, assumptions: TradeAssumptions = TradeAssumptions()):
    """Per-trade simulated net P&L in USD, vectorized.

    ``exec_price = min(entry_price + slippage, max_price)``; ``pnl = n * (won - exec_price) - fee(n, exec_price)``,
    where a winning contract pays 1.00. Identical to the formula in ``src/momentum.py::replay``.
    """
    p = np.asarray(entry_price, dtype="float64")
    w = np.asarray(won, dtype="float64")
    if ((p < 0) | (p > 1)).any():
        raise ValueError("entry prices must lie in [0, 1]")
    ex = np.minimum(p + assumptions.slippage_usd, assumptions.max_price)
    n = assumptions.contracts_per_trade
    return n * (w - ex) - kalshi_taker_fee(ex, n, assumptions.fee_rate)


def max_drawdown(pnl) -> float:
    """Largest peak-to-trough fall (USD, >= 0) of cumulative P&L in the given order; the peak starts at 0.

    Order matters: pass trades sorted chronologically. Empty input gives 0.0.
    """
    x = np.asarray(pnl, dtype="float64")
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return 0.0
    cum = np.cumsum(x)
    peak = np.maximum.accumulate(np.concatenate(([0.0], cum)))[1:]
    return float((peak - cum).max())


def summarize_simulated_trades(entry_price, won, assumptions: TradeAssumptions = TradeAssumptions(),
                               market_ids=None) -> dict:
    """Aggregate summary of SIMULATED trades given in chronological order.

    Reports counts, win rate with Wilson interval, EV per contract (mean net P&L / contracts, with standard error),
    net P&L and max drawdown, plus the assumptions used. ``n_markets`` is reported when ``market_ids`` is given.
    """
    p = np.asarray(entry_price, dtype="float64").ravel()
    w = np.asarray(won, dtype="float64").ravel()
    if p.shape != w.shape:
        raise ValueError("entry_price and won must have the same length")
    ok = np.isfinite(p) & np.isfinite(w)
    ids = None if market_ids is None else np.asarray(market_ids).ravel()[ok]
    p, w = p[ok], w[ok]
    n = int(len(p))
    res = {"source": "simulated", "assumptions": asdict(assumptions), "n_trades": n,
           "n_markets": int(pd.Series(ids).nunique()) if ids is not None else None}
    if n == 0:
        res.update(wins=0, win_rate=NAN, win_rate_ci_lo=NAN, win_rate_ci_hi=NAN, ev_per_contract_usd=NAN,
                   ev_se_usd=NAN, net_pnl_usd=0.0, max_drawdown_usd=0.0)
        return res
    pnl = simulate_trade_pnl(p, w, assumptions)
    wins = int(w.sum())
    lo, hi = wilson_interval(wins, n)
    per_contract = pnl / assumptions.contracts_per_trade
    res.update(
        wins=wins, win_rate=wins / n, win_rate_ci_lo=lo, win_rate_ci_hi=hi,
        ev_per_contract_usd=float(per_contract.mean()),
        ev_se_usd=float(per_contract.std(ddof=1) / np.sqrt(n)) if n > 1 else NAN,
        net_pnl_usd=float(pnl.sum()), max_drawdown_usd=max_drawdown(pnl),
    )
    return res
