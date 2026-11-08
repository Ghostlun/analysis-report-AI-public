"""Technical indicators on the resampled BTC reference-price series (close-only index levels).

Conventions
  * Inputs are bar closes (``pd.Series``), optionally with ``segments`` (from ``resample_reference``). A calculation never
    spans a segment change or a NaN: each contiguous non-null run is processed independently and restarts warm-up.
  * Values are causal: the value at bar ``t`` depends only on closes at or before ``t``.
  * Unavailable values (warm-up, invalid input) are NaN. Outputs are never +/-inf.
  * Not implemented, by design: ATR (no OHLC bars), VWAP/OBV/volume indicators (no BTC spot volume).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MINUTES_PER_YEAR = 365 * 24 * 60  # BTC trades 24/7


def bars_per_year(bar_minutes: float) -> float:
    """Number of bars per calendar year assuming continuous (24/7, 365-day) trading."""
    if bar_minutes <= 0:
        raise ValueError("bar_minutes must be positive")
    return MINUTES_PER_YEAR / bar_minutes


def _check_window(window: int, minimum: int = 1) -> None:
    if not isinstance(window, (int, np.integer)) or isinstance(window, bool) or window < minimum:
        raise ValueError(f"window must be an integer >= {minimum}")


def _run_ids(close: pd.Series, segments: pd.Series | None) -> np.ndarray:
    """Id of each contiguous run of valid (finite, > 0) closes within a segment; -1 for invalid values."""
    v = close.to_numpy(dtype="float64")
    ok = np.isfinite(v) & (v > 0)
    seg = np.zeros(len(v), dtype="int64") if segments is None else pd.Series(segments).to_numpy()
    new = np.ones(len(v), dtype=bool)
    if len(v) > 1:
        new[1:] = (seg[1:] != seg[:-1]) | ~ok[:-1] | ~ok[1:]
    ids = np.cumsum(new)
    ids = np.where(ok, ids, -1)
    return ids


def _apply_by_run(close: pd.Series, segments, func) -> pd.Series:
    """Apply ``func(values: ndarray) -> ndarray`` to every contiguous valid run; NaN elsewhere."""
    v = close.to_numpy(dtype="float64")
    out = np.full(len(v), np.nan)
    ids = _run_ids(close, segments)
    for rid in np.unique(ids[ids >= 0]):
        pos = np.flatnonzero(ids == rid)
        out[pos] = func(v[pos])
    out[~np.isfinite(out)] = np.nan
    return pd.Series(out, index=close.index, dtype="float64")


def sma(close: pd.Series, window: int, segments=None) -> pd.Series:
    """Simple moving average of the last ``window`` closes (USD). First ``window - 1`` values of a run are NaN."""
    _check_window(window)

    def f(x):
        return pd.Series(x).rolling(window, min_periods=window).mean().to_numpy()
    return _apply_by_run(close, segments, f)


def ema(close: pd.Series, window: int, segments=None) -> pd.Series:
    """Exponential moving average, ``alpha = 2 / (window + 1)``, seeded with the SMA of the first ``window`` closes.

    Warm-up: the first ``window - 1`` values of a run are NaN; the value at index ``window - 1`` equals that SMA.
    """
    _check_window(window)
    alpha = 2.0 / (window + 1)

    def f(x):
        out = np.full(len(x), np.nan)
        if len(x) < window:
            return out
        out[window - 1] = x[:window].mean()
        for i in range(window, len(x)):
            out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
        return out
    return _apply_by_run(close, segments, f)


def pct_return(close: pd.Series, periods: int = 1, segments=None) -> pd.Series:
    """Simple percentage return over ``periods`` bars: ``100 * (C_t / C_{t-periods} - 1)`` (percent)."""
    _check_window(periods)

    def f(x):
        out = np.full(len(x), np.nan)
        if len(x) > periods:
            out[periods:] = 100.0 * (x[periods:] / x[:-periods] - 1.0)
        return out
    return _apply_by_run(close, segments, f)


def roc(close: pd.Series, window: int, segments=None) -> pd.Series:
    """Rate of change over ``window`` bars in percent. Same formula as ``pct_return(close, window)``."""
    return pct_return(close, window, segments)


def rsi(close: pd.Series, window: int = 14, segments=None) -> pd.Series:
    """Relative Strength Index with Wilder smoothing (0-100).

    The first value needs ``window + 1`` closes: the seed averages are the plain means of the first ``window`` gains and
    losses, then ``avg = (prev * (window - 1) + x) / window``.
    Flat-price convention: ``avg_gain == avg_loss == 0`` gives 50.0 (neutral); losses only gives 0.0; gains only gives 100.0.
    """
    _check_window(window)

    def f(x):
        out = np.full(len(x), np.nan)
        if len(x) <= window:
            return out
        d = np.diff(x)
        gain, loss = np.clip(d, 0, None), np.clip(-d, 0, None)
        ag, al = gain[:window].mean(), loss[:window].mean()

        def val(ag, al):
            if ag == 0 and al == 0:
                return 50.0
            if al == 0:
                return 100.0
            return 100.0 - 100.0 / (1.0 + ag / al)
        out[window] = val(ag, al)
        for i in range(window, len(d)):
            ag = (ag * (window - 1) + gain[i]) / window
            al = (al * (window - 1) + loss[i]) / window
            out[i + 1] = val(ag, al)
        return out
    return _apply_by_run(close, segments, f)


def realized_volatility(close: pd.Series, window: int, segments=None, annualize_bars_per_year: float | None = None) -> pd.Series:
    """Rolling realized volatility of log returns, in PERCENT.

    ``r_t = ln(C_t / C_{t-1})``; per-bar volatility = ``sqrt(mean(r^2))`` over the last ``window`` returns (zero-mean
    assumption, not demeaned). Needs ``window + 1`` closes. Unit: percent per bar when ``annualize_bars_per_year`` is
    None; otherwise multiplied by ``sqrt(annualize_bars_per_year)`` (percent per year; see ``bars_per_year``).
    Annualization assumes independent returns and 24/7 trading; short samples give very noisy annualized values.
    A perfectly flat series returns 0.0 (valid, not NaN).
    """
    _check_window(window)
    if annualize_bars_per_year is not None and not annualize_bars_per_year > 0:
        raise ValueError("annualize_bars_per_year must be positive")
    scale = 1.0 if annualize_bars_per_year is None else float(np.sqrt(annualize_bars_per_year))

    def f(x):
        out = np.full(len(x), np.nan)
        if len(x) <= window:
            return out
        r2 = np.diff(np.log(x)) ** 2
        m = pd.Series(r2).rolling(window, min_periods=window).mean().to_numpy()
        out[1:] = 100.0 * scale * np.sqrt(m)
        return out
    return _apply_by_run(close, segments, f)


def compute_indicators(
    bars: pd.DataFrame,
    sma_windows=(20,),
    ema_windows=(20,),
    rsi_window: int = 14,
    roc_windows=(12,),
    vol_windows=(24,),
    annualize: bool = False,
    bar_minutes: float | None = None,
    include_partial: bool = False,
    include_gap_affected: bool = False,
) -> pd.DataFrame:
    """Indicator table for bars from ``resample_reference`` (uses ``close`` and ``segment``).

    Partial bars and bars overlapping a collection gap are excluded (close treated as missing, which also restarts
    warm-up) unless ``include_partial`` / ``include_gap_affected``. With ``annualize`` the realized volatility is
    annualized and ``bar_minutes`` is required.
    """
    close = bars["close"].astype("float64")
    if "partial" in bars.columns and not include_partial:
        close = close.where(~bars["partial"].astype(bool))
    if "gap_affected" in bars.columns and not include_gap_affected:
        close = close.where(~bars["gap_affected"].astype(bool))
    seg = bars["segment"] if "segment" in bars.columns else None
    ann = None
    if annualize:
        if bar_minutes is None:
            raise ValueError("bar_minutes is required to annualize")
        ann = bars_per_year(bar_minutes)
    out = pd.DataFrame({"close": close})
    for w in sma_windows:
        out[f"sma_{w}"] = sma(close, w, seg)
    for w in ema_windows:
        out[f"ema_{w}"] = ema(close, w, seg)
    out[f"rsi_{rsi_window}"] = rsi(close, rsi_window, seg)
    for w in roc_windows:
        out[f"roc_{w}_pct"] = roc(close, w, seg)
    suffix = "ann_pct" if annualize else "bar_pct"
    for w in vol_windows:
        out[f"realized_vol_{w}_{suffix}"] = realized_volatility(close, w, seg, ann)
    return out
