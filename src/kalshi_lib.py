"""Shared loading, feature and simulation helpers for the KXBTC15M strategy analysis.

Read-only: reads KXBTC15M_all.csv only. No network access, no orders, no application code is imported.
Fee/sizing logic mirrors backend/app/services/order_preview.py (taker_fee) and paper_trading.py (plan_fill).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from functools import lru_cache

import numpy as np
import pandas as pd

from paths import MARKET_CSV

CSV = str(MARKET_CSV)
BUDGET = Decimal("5.00")
FEE_RATE = Decimal("0.07")
FEE_MULT = Decimal("1")
MICRO = Decimal("0.000001")
CENT = Decimal("0.01")
SLIP = 0.01
CAP = Decimal("0.99")


def _ceil(x: Decimal, grid: Decimal) -> Decimal:
    return (x / grid).to_integral_value(rounding=ROUND_CEILING) * grid


def fee(n: int, p: Decimal) -> Decimal:
    """ceil_6dp(0.07 * n * p * (1-p) * multiplier) - order_preview.taker_fee for one fill level."""
    return _ceil(FEE_RATE * n * p * (1 - p) * FEE_MULT, MICRO)


@lru_cache(maxsize=None)
def size_buy(p_exec_milli: int, p_quote_milli: int, budget_cents: int = 500) -> tuple[int, float, float]:
    """Largest whole-contract n with debit <= budget; returns (n, contracts_cost, total_debit_rounded_up_to_cent).

    Mirrors paper_trading.plan_fill/spend_for: cost at the (slipped) executable price, fee = max(fee at slipped,
    fee at quoted), total debit rounded UP to $0.01.
    """
    p = min(Decimal(p_exec_milli) / 1000, CAP)
    q = Decimal(p_quote_milli) / 1000
    budget = Decimal(budget_cents) / 100
    best = (0, 0.0, 0.0)
    n = 0
    while True:
        n += 1
        cost = p * n
        f = max(fee(n, p), fee(n, q))
        total = _ceil(cost + f, CENT)
        if total > budget or n > 1000:
            break
        best = (n, float(cost), float(total))
    return best


@lru_cache(maxsize=None)
def sell_fee(n: int, bid_milli: int) -> float:
    return float(fee(n, Decimal(bid_milli) / 1000))


def milli(x: float) -> int:
    return int(round(x * 1000))


# ---------------------------------------------------------------------------------------------
@dataclass
class Market:
    ticker: str
    close: pd.Timestamp
    day: str
    result: int | None  # 1 = YES, 0 = NO, None = no official settlement
    sec: np.ndarray
    yb: np.ndarray
    ya: np.ndarray
    nb: np.ndarray
    na: np.ndarray
    diff: np.ndarray  # BRTI - strike (NaN if reference missing)
    ref_ok: bool = False
    feat: dict = field(default_factory=dict)


def load_markets() -> tuple[list[Market], pd.DataFrame]:
    df = pd.read_csv(CSV)
    df["collected_at_utc"] = pd.to_datetime(df["collected_at_utc"], utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    df["sec"] = (df["close_time"] - df["collected_at_utc"]).dt.total_seconds()
    pre = df[df["sec"] >= 0].sort_values(["ticker", "collected_at_utc"])  # decision-time data only: before close
    markets: list[Market] = []
    for tk, g in pre.groupby("ticker", sort=False):
        res = g["official_settlement_result"].dropna().str.lower().unique()
        r = None if len(res) != 1 else (1 if res[0] == "yes" else 0)
        close = g["close_time"].iloc[0]
        m = Market(tk, close, close.strftime("%Y-%m-%d"), r, g["sec"].to_numpy(), g["yes_bid_usd"].to_numpy(float),
                   g["yes_ask_usd"].to_numpy(float), g["no_bid_usd"].to_numpy(float), g["no_ask_usd"].to_numpy(float),
                   g["btc_price_difference_usd"].to_numpy(float))
        m.ref_ok = bool(np.isfinite(m.diff).mean() > 0.8)
        markets.append(m)
    markets.sort(key=lambda m: m.close)
    return markets, df


def add_features(m: Market) -> None:
    """Per-snapshot features using only rows at or before each snapshot (earlier in time = larger sec)."""
    n = len(m.sec)
    d = m.diff
    side = np.where(np.isnan(d), 0, np.sign(d)).astype(int)  # +1 YES favoured by BTC, -1 NO
    ask = np.where(side > 0, m.ya, np.where(side < 0, m.na, np.nan))
    bid = np.where(side > 0, m.yb, np.where(side < 0, m.nb, np.nan))
    dist = np.abs(d)
    stable60 = np.zeros(n, bool)
    move60 = np.full(n, np.nan)
    ask_slope60 = np.full(n, np.nan)
    ask_slope30 = np.full(n, np.nan)
    for i in range(n):
        if side[i] == 0:
            continue
        # window of rows within the previous 60s (and the row itself)
        j = i
        ok = True
        while j >= 0 and m.sec[j] <= m.sec[i] + 60.5:
            if side[j] != side[i]:
                ok = False
                break
            j -= 1
        # require history to actually span >= 45s (not just a short window)
        stable60[i] = ok and (j + 1 < i) and (m.sec[j + 1] - m.sec[i] >= 45)
        # reference row ~60s earlier (within 20s), mirrors paper_strategy._reference_point
        k = i
        while k >= 0 and m.sec[k] < m.sec[i] + 60:
            k -= 1
        if k >= 0 and (m.sec[k] - (m.sec[i] + 60)) <= 20 and np.isfinite(d[k]):
            move60[i] = side[i] * (d[i] - d[k])
        # ask slope on the favoured side (price per second), mirrors evaluate_momentum_entry
        for lb, arr in ((30, ask_slope30), (60, ask_slope60)):
            k = i
            while k >= 0 and m.sec[k] < m.sec[i] + lb:
                k -= 1
            if k >= 0 and (m.sec[k] - (m.sec[i] + lb)) <= 20:
                a0 = (m.ya if side[i] > 0 else m.na)[k]
                if np.isfinite(a0) and np.isfinite(ask[i]):
                    arr[i] = (ask[i] - a0) / (m.sec[k] - m.sec[i])
    m.feat = dict(side=side, ask=ask, bid=bid, dist=dist, stable60=stable60, move60=move60,
                  slope30=ask_slope30, slope60=ask_slope60)


# --------------------------------------------------------------------------------------------
@dataclass
class Trade:
    ticker: str
    day: str
    close: pd.Timestamp
    side: int  # +1 YES, -1 NO
    n: int
    entry_sec: float
    ask_q: float
    price: float
    debit: float
    exit_kind: str
    exit_sec: float | None
    proceeds: float
    win: bool | None  # settlement outcome for the side held (None if exited early)
    held_win: bool  # would the side have won at settlement
    pnl: float


SCEN = {
    # name: (delay_snapshots, extra_slippage, depth_cap)
    "S0_quoted": (0, 0.0, None),
    "S1_project": (0, SLIP, None),  # +$0.01/contract as in paper_trading.SLIPPAGE
    "S2_delay15s": (1, SLIP, None),  # fill at the next snapshot (~15s later) + $0.01
    "S3_delay_worse": (1, 0.03, None),
    "S4_thin_book": (0, SLIP, 3),  # only 3 contracts assumed available
}


def buy_fill(m: Market, i: int, side: int, scen: str, min_sec: float = 0.0):
    """Return (n, price, debit, fill_row, ask_quote) or None if unfillable."""
    delay, slip, cap = SCEN[scen]
    k = i + delay
    if k >= len(m.sec) or m.sec[k] < min_sec:
        return None
    a_quote = (m.ya if side > 0 else m.na)[k]
    if not np.isfinite(a_quote) or a_quote <= 0:
        return None
    if delay:  # IOC limit = decision-time ask + slippage; a faster-moving quote is a missed fill (quote_moved)
        a_dec = (m.ya if side > 0 else m.na)[i]
        if np.isfinite(a_dec) and a_quote > a_dec + slip + 1e-9:
            return None
    price = min(a_quote + slip, 0.99)
    n, cost, debit = size_buy(milli(price), milli(a_quote))
    if cap is not None and n > cap:
        n = cap
        p = Decimal(milli(price)) / 1000
        cost = float(p * n)
        debit = float(_ceil(p * n + max(fee(n, p), fee(n, Decimal(milli(a_quote)) / 1000)), CENT))
    if n < 1:
        return None
    return n, price, debit, k, a_quote


def settle(m: Market, side: int, n: int, debit: float) -> tuple[bool, float]:
    won = (m.result == 1) if side > 0 else (m.result == 0)
    return won, (n if won else 0.0) - debit


def sell_fill(m: Market, i: int, side: int, scen: str, n: int):
    """Sell n at the executable bid of the held side (delayed per scenario, minus slippage). None if no bid."""
    delay, slip, _ = SCEN[scen]
    k = i + delay
    if k >= len(m.sec):
        return None
    b = (m.yb if side > 0 else m.nb)[k]
    if not np.isfinite(b) or b <= 0:
        return None
    px = max(b - slip, 0.001)
    proceeds = n * px - sell_fee(n, milli(px))
    return proceeds, k


def run_strategy(markets, entry_fn, scen="S1_project", exit_fn=None, min_entry_sec=20.0) -> tuple[list[Trade], dict]:
    """One entry per market. entry_fn(m) -> (row_index, side) or None. exit_fn(m, i_fill, side, n, price) -> row index
    of first exit trigger or None."""
    trades, skipped = [], {"no_signal": 0, "unfillable": 0}
    for m in markets:
        sig = entry_fn(m)
        if sig is None:
            skipped["no_signal"] += 1
            continue
        i, side = sig
        f = buy_fill(m, i, side, scen, min_sec=min_entry_sec if SCEN[scen][0] else 0.0)
        if f is None:
            skipped["unfillable"] += 1
            continue
        n, price, debit, k, aq = f
        won_hold, pnl_hold = settle(m, side, n, debit)
        kind, esec, proceeds, pnl = "settlement", None, (n if won_hold else 0.0), pnl_hold
        if exit_fn is not None:
            j = exit_fn(m, k, side, n, aq)
            if j is not None:
                sf = sell_fill(m, j, side, scen, n)
                if sf is not None:
                    proceeds, kk = sf
                    kind, esec, pnl = "early_exit", float(m.sec[kk]), proceeds - debit
        trades.append(Trade(m.ticker, m.day, m.close, side, n, float(m.sec[i]), aq, price, debit, kind, esec, proceeds,
                            None if kind == "early_exit" else won_hold, won_hold, pnl))
    return trades, skipped


# --------------------------------------------------------------------------------------------
def summarize(trades: list[Trade], n_eligible: int, skipped: dict | None = None, boot=2000, seed=7) -> dict:
    out = {"eligible": n_eligible, "trades": len(trades), "skipped": n_eligible - len(trades)}
    if not trades:
        return out | {"net": 0.0, "spend": 0.0}
    t = pd.DataFrame([x.__dict__ for x in trades]).sort_values("close").reset_index(drop=True)
    pnl = t["pnl"].to_numpy()
    spend = t["debit"].to_numpy()
    held = t["held_win"].to_numpy(bool)
    wins_pnl = pnl > 0
    n = len(t)
    out.update(
        trades=n,
        win_rate=float(wins_pnl.mean()),  # profitable trades
        settle_win_rate=float(held.mean()),  # side finished in the money at settlement (hold basis)
        breakeven_wr=float((spend / t["n"].to_numpy()).mean()),  # avg debit per contract incl. fees = P(win) needed
        net=float(pnl.sum()), avg=float(pnl.mean()), spend=float(spend.sum()), roi=float(pnl.sum() / spend.sum()),
        avg_price=float((t["price"]).mean()), avg_n=float(t["n"].mean()),
    )
    cum = np.cumsum(pnl)
    out["max_dd"] = float((np.maximum.accumulate(np.maximum(cum, 0)) - cum).max())
    streak = best = 0
    for v in pnl:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    out["max_lose_streak"] = int(best)
    daily = t.groupby("day")["pnl"].sum()
    out["days"] = int(len(daily))
    out["days_pos"] = int((daily > 0).sum())
    out["daily"] = daily.round(2).to_dict()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(boot, n))
    sums = pnl[idx].sum(1)
    sp = spend[idx].sum(1)
    out["net_ci"] = (float(np.percentile(sums, 2.5)), float(np.percentile(sums, 97.5)))
    out["roi_ci"] = (float(np.percentile(sums / sp, 2.5)), float(np.percentile(sums / sp, 97.5)))
    out["p_roi_le0"] = float((sums / sp <= 0).mean())
    # Wilson interval for settlement win rate
    z = 1.96
    p = held.mean()
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    out["wr_ci"] = (float(c - h), float(c + h))
    out["early_exits"] = int((t["exit_kind"] == "early_exit").sum())
    return out

