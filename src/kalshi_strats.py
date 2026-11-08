"""Entry/exit rule factories. Every rule only reads rows at or before the decision row (no look-ahead)."""
import numpy as np
from kalshi_lib import *


def baseline_95force(force_sec=60, min_ask=0.95):
    """five_minute_95cent_force_v1 (default live strategy): evaluate_five_minute_95cent_force replay on snapshots."""
    def f(m):
        forced_done = False
        for i in range(len(m.sec)):
            s = m.sec[i]
            if s > 300 or s < 20:
                continue
            d = m.diff[i]
            forced = s <= force_sec
            if forced:
                ym = (m.yb[i] + m.ya[i]) / 2
                nm = (m.nb[i] + m.na[i]) / 2
                if np.isfinite(ym) and np.isfinite(nm) and ym != nm:
                    side = 1 if ym > nm else -1
                elif np.isfinite(d) and d != 0:
                    side = 1 if d > 0 else -1
                else:
                    return None  # single forced attempt consumed
                ask = (m.ya if side > 0 else m.na)[i]
                return (i, side) if np.isfinite(ask) else None
            if not np.isfinite(d) or d == 0:
                continue
            side = 1 if d > 0 else -1
            ask = (m.ya if side > 0 else m.na)[i]
            if np.isfinite(ask) and ask >= min_ask:
                return i, side
        return None
    return f


def baseline_price_threshold(final_sec=60, min_diff=2.0, min_ask=0.90):
    def f(m):
        for i in range(len(m.sec)):
            s = m.sec[i]
            if s > 300 or s < 20:
                continue
            d = m.diff[i]
            if not np.isfinite(d):
                continue
            if s <= final_sec:
                if abs(d) < min_diff:
                    continue
                side = 1 if d > 0 else -1
                ask = (m.ya if side > 0 else m.na)[i]
                if np.isfinite(ask) and ask > 0:
                    return i, side
                continue
            if d == 0:
                continue
            side = 1 if d > 0 else -1
            ask = (m.ya if side > 0 else m.na)[i]
            if np.isfinite(ask) and ask >= min_ask:
                return i, side
        return None
    return f


def baseline_momentum():
    """five_minute_momentum_v1: ask>=0.95 standard, or 0.90<=ask<0.95 with sustained positive ask slope."""
    def f(m):
        ft = m.feat
        for i in range(len(m.sec)):
            s = m.sec[i]
            if s > 300 or s < 20:
                continue
            side = ft["side"][i]
            ask = ft["ask"][i]
            if side == 0 or not np.isfinite(ask):
                continue
            if ask >= 0.95:
                return i, int(side)
            if ask < 0.90:
                continue
            sl, ll = ft["slope30"][i], ft["slope60"][i]
            if not (np.isfinite(sl) and np.isfinite(ll)):
                continue
            if sl <= 0 or ll <= 0 or sl < 0.8 * ll:
                continue
            tt = (0.95 - ask) / ll
            if 0 <= tt <= min(60.0, s):
                return i, int(side)
        return None
    return f


def baseline_direction():
    def f(m):
        for i in range(len(m.sec)):
            s = m.sec[i]
            if s > 300 or s < 20:
                continue
            d = m.diff[i]
            if np.isfinite(d) and d != 0:
                side = 1 if d > 0 else -1
                return (i, side) if np.isfinite((m.ya if side > 0 else m.na)[i]) else None
        return None
    return f


def rule(t_hi, t_lo=30.0, a_lo=0.0, a_hi=0.99, dist_min=0.0, stable=False, move_min=None, z_min=None, sigma=None,
         slope_pos=False):
    """First snapshot with t_lo <= sec <= t_hi where the BTC-favoured side's ask is in [a_lo, a_hi] and filters pass."""
    def f(m):
        ft = m.feat
        for i in range(len(m.sec)):
            s = m.sec[i]
            if s > t_hi or s < t_lo:
                continue
            side = ft["side"][i]
            ask = ft["ask"][i]
            if side == 0 or not np.isfinite(ask) or not (a_lo <= ask <= a_hi):
                continue
            if ft["dist"][i] < dist_min:
                continue
            if stable and not ft["stable60"][i]:
                continue
            if move_min is not None and not (np.isfinite(ft["move60"][i]) and ft["move60"][i] >= move_min):
                continue
            if z_min is not None and ft["dist"][i] / (sigma * np.sqrt(max(s, 1.0))) < z_min:
                continue
            if slope_pos and not (np.isfinite(ft["slope60"][i]) and ft["slope60"][i] > 0):
                continue
            return i, int(side)
        return None
    return f


def price_only_rule(t_hi, t_lo=30.0, a_lo=0.90, a_hi=0.99):
    """No BTC data needed: buy the side whose ask is the higher one and within [a_lo, a_hi]."""
    def f(m):
        for i in range(len(m.sec)):
            s = m.sec[i]
            if s > t_hi or s < t_lo:
                continue
            for side, ask in ((1, m.ya[i]), (-1, m.na[i])):
                if np.isfinite(ask) and a_lo <= ask <= a_hi:
                    return i, side
        return None
    return f


# --- exits ---------------------------------------------------------------------------------
def exit_rule(tp=None, sl_drop=None, flip=False, time_sec=None, flip_dist=0.0, tp_min_sec=0.0):
    """First snapshot AFTER the entry fill row where a trigger fires (decision uses that snapshot's data;
    execution is then simulated by sell_fill with the scenario's delay/slippage)."""
    def f(m, k, side, n, ask_q):
        bids = m.yb if side > 0 else m.nb
        for j in range(k + 1, len(m.sec)):
            b = bids[j]
            if time_sec is not None and m.sec[j] <= time_sec:
                return j if np.isfinite(b) else None
            if tp is not None and np.isfinite(b) and b >= tp:
                return j
            if sl_drop is not None and np.isfinite(b) and b <= ask_q - sl_drop:
                return j
            if flip and np.isfinite(m.diff[j]) and side * m.diff[j] < -flip_dist:
                return j
        return None
    return f
