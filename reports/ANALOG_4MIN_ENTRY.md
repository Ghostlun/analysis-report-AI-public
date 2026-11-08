# Analog 4-minute entry: spec for prod

Goal: at ~4 minutes before close, look at the shape of the BTC-vs-strike gap, compare it to past markets (analogs), get P(YES) and P(NO) = 1 - P(YES), and **always buy the side with the higher probability** (no probability threshold, no skipping). Offline analysis only; this repo does not trade.

## Rule
1. Decision time: the 15 s snapshot closest to **240 s before close** (accept 225-255 s). One decision per market, no re-entry.
2. Compute the 7 features below from data up to that snapshot only.
3. `p_yes` = analog probability (k-NN, below), `p_no = 1 - p_yes`. Buy YES if `p_yes >= 0.5`, else NO; `prob = max(p_yes, p_no)`.
4. **Buy that side at the ask, no probability threshold** (config `min_prob`, default 0.5 = always enter; it can be raised later without redeploy, see results below).
5. Hold to settlement. The only technical skip: ask + slippage would exceed $0.99 (nothing left to win), or missing data.

## Features (`pct` = `100*ln(reference_price / floor_strike)`)
Computed on the 15 s snapshots, `i` = decision snapshot:
- `sec`: seconds to close
- `sigma`: std of `pct[j+1]-pct[j]` over the last 20 snapshots up to `i`, floored at 1e-4
- `z = pct[i] / (sigma * sqrt(sec/15))`
- `d_n = (pct[i] - pct[i-n]) / (sigma * sqrt(n))` for n = 2, 4, 8, 12, 20 snapshots (~30/60/120/180/300 s)

Model features, in order: `z, sec, d2, d4, d8, d12, d20` (`pct` and `sigma` are inputs to those, not model features).

## Model (analog = nearest neighbours)
- Standardize features with `scaler_mean` / `scaler_scale`, find the 150 nearest past snapshots (Euclidean), weight by 1/distance, and `p_yes` = weighted share that settled YES. If a distance is exactly 0, use only those rows.
- Files (regenerate with `python run.py model`):
  - `outputs/simulated/analog_model.json`: parameters, scaler, feature definitions
  - `outputs/simulated/analog_model_train.csv`: 33,415 training snapshots (`z,sec,d2,d4,d8,d12,d20,y`), all 982 markets, `sec` 30-600
- Reference scorer: `pattern_model.score_analog(spec, train, features)` (numpy only, identical to scikit-learn's `KNeighborsClassifier(weights='distance')`; verified, max difference 2e-7).
- Training uses snapshots from 30-600 s, so `sec` is a feature; this is the model that was validated.
- Refit as data grows: rerun `python scripts/update_data.py` then `python run.py model`.

## Validated results
Fit on dev (333 markets before 2026-10-27), decision at ~240 s on the 649 test markets, fee 0.07*p*(1-p), +$0.01 slippage.

**Always enter (no threshold), analog side:** 518 trades (131 markets had ask + 1c > $0.99 and were not tradeable), win rate 77.2%, avg price 0.782, **EV -0.019 per contract (SE 0.016)**; with a 15 s later fill -0.031. Always buying the market leader gives -0.016, so always entering does not beat the market; it is about break-even-to-slightly-negative.

By analog probability of the chosen side (test):

| prob bucket | Trades | Win rate | Avg price | EV per contract |
|---|---|---|---|---|
| 0.5-0.6 | 87 | 50.6% | 0.570 | -0.079 |
| 0.6-0.7 | 99 | 62.6% | 0.671 | -0.058 |
| 0.7-0.8 | 133 | 81.2% | 0.805 | -0.003 |
| 0.8-0.9 | 126 | 92.1% | 0.902 | +0.013 |
| 0.9-0.93 | 62 | 96.8% | 0.958 | +0.007 |
| 0.93-1.0 | 142 | 98.6% | 0.975 | +0.009 |

The probability is well calibrated (win rate tracks prob), so it is usable as a confidence number, but all the loss comes from the 0.5-0.7 buckets (~186 trades, EV -0.06 to -0.08) and all the gain from 0.8+. Earlier threshold variant (same setup): prob >= 0.93 gave 57 trades, 98.3% win, +0.027 (SE 0.015), +0.024 with a 15 s later fill; prob >= 0.95 gave 42 trades, +0.022.
The analog side equals the market leader in 90% of the markets.

## Risks (read before sizing)
- Entering every market with no threshold is expected to lose ~2 c per contract (about -$0.02 x contracts per market), with about 1 loss in 4-5 trades at an average price of 0.78 (a loss costs ~$0.78 per contract).
- Since you do not want skips, log `prob` on every trade: after the first few hundred markets we can see the real win rate per bucket and raise `min_prob` (for example 0.8) with a config change, no redeploy.
- The edge in the 0.8+ buckets is small (+0.7 to +1.3 c) and within about 1 standard error each; only 57 trades had prob >= 0.93 (+0.027, ~1.8 SE). The exported model is fit on all data, so there is no untouched sample for it.
- Quotes at 4 minutes may differ from the 15 s snapshot ask; slippage beyond $0.01 would remove any edge.
- Recommended sizing: very small, log every decision (`features`, `p_yes`, `p_no`, ask, fill, result).
