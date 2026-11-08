# KXBTC15M timing, probability and pattern-model analysis

Data: `data/raw/KXBTC15M_all.csv` (985 markets, 15 s snapshots) and `data/raw/live_orders_all.csv` (373 settled momentum_v1 live trades).
All results are SIMULATED unless marked ACTUAL. Dev = markets first seen before 2026-10-27, test = on/after. Costs: fee 0.07*p*(1-p), +$0.01 slippage unless noted.
Scratch analyses (timing, crossings, scalping, reach) were run ad hoc; only the pattern model is reproducible via `python run.py model`.

## 1. Status of momentum v1/v2 on the refreshed data
`python run.py check` fails: the numbers in `MOMENTUM_V2_ANALYSIS.md` were computed on the 2026-10-30 snapshot.

| Metric | Old report | Current data |
|---|---|---|
| ACTUAL settled trades / net P&L / fees | 146 / -$6.03 / $2.94 | 373 / -$29.58 / $10.68 |
| Test v1 (trades / net) | 342 / -$19.95 | 633 / -$41.66 |
| Test v2 (trades / net / maxdd) | 145 / +$0.13 / $9.8 | 292 / -$14.30 / $21.4 |

v2 is better than v1 on test (+$27 paired, 95% CI -$16..+$75, not significant) but is not profitable.
A grid of 154 v2 variants restricted to ask < 0.97 had no variant positive on both dev and test; dev/test EV correlation was 0.11, i.e. dev selection is mostly noise.

## 2. How early is the leader right?
Leader = side with mid > 0.5. Accuracy vs seconds to close (30 s bins):

| To close | Leader wins | Avg leader price |
|---|---|---|
| 12 min | 58% | 0.61 |
| 10 min | 68% | 0.70 |
| 6 min | 78% | 0.80 |
| 4 min | 85% | 0.84 |
| 2 min | ~90% | 0.90 |
| 45 s | ~95% | 0.95 |
| 15 s | ~98% | 0.98 |

First bin with accuracy >= 90%: ~105 s; >= 95%: ~45 s; >= 98%: ~15 s; 99% never reached. Late bins have fewer rows (decided markets drop out), so the late numbers may be understated.
Win rate ~= price in every bin (gap within +-0.01): the market is already calibrated, so time alone gives no edge.

## 3. 0.5 crossings
Mean 3.2 crossings of 0.5 per market (23% none, 28% five or more). Using only information available at the time: more crossings so far means a less reliable leader (300 s before close: 0-1 crossings 85-88%, 5+ crossings 66%). The size of the lead (|mid-0.5|) matters more than the crossing count (<0.05: 51-60%, >=0.30: 85-95%).

## 4. Where is there edge by price? (hold to settlement, buy leader ask)
- 0.85-0.93 ask (win rate ~90%): EV per contract -0.02 to -0.04; breakeven win rate is price + fee, and the market prices it fairly.
- Only consistent positive cell: ask >= 0.98 with <= 150 s left: win rate 99.4-100%, EV +0.002 to +0.007 per contract (tiny); one loss costs ~$0.99, about 100 wins.
- 4-10 min before close: EV negative in almost every price band (-0.02 to -0.06).
- Fee at 0.97 is only ~0.2 c; the thin margin comes from win rate ~= price, not from fees.

## 5. Price-swing trading (not holding to settlement)
108 combos (entry band 0.3-0.9, take-profit +0.03/+0.05/+0.10, stop none/-0.05/-0.10, two time windows): none positive on both dev and test (EV mostly -0.03 to -0.07). Round-trip cost (spread + fees + slippage) is 3-5 c, above the target.
Example: after first touching ask 0.80-0.85, bid reaches 0.90 in 85.7% of 854 cases (median 135 s), but the other 14% mostly lose ~$0.83, so EV ~ -$0.08 per contract (breakeven needs ~94%).

## 6. Pattern/probability model (`src/pattern_model.py`, `python run.py model`)
Feature definition (all computed only from data up to the snapshot):
- `pct = 100*ln(reference_price/floor_strike)`
- `sigma` = std of snapshot-to-snapshot change of `pct` over the last 20 snapshots, floored at 1e-4
- `z = pct / (sigma*sqrt(sec/15))`, `sec` = seconds to close
- `d_k = (pct_now - pct_{now-k snapshots}) / (sigma*sqrt(k))` for k = 2, 4, 8, 12, 20 snapshots
Models: logistic regression, gradient boosting, k-NN analogs (k=150), fit on dev (333 markets), judged on test (649 markets).

Findings (test):
- Brier score and directional accuracy are equal to or worse than the market mid in every time bin (e.g. 240-300 s: market 0.123, logit 0.122, GBM 0.123, k-NN 0.130). The models add no information beyond the market price.
- Entry policy (buy a side when model probability > ask + slippage + fee + margin; one entry per market): EV per contract +0.01 to +0.16 with immediate fills (logit margin 0.12: +0.07 to +0.16, SE ~0.03).
- With a 15 s fill delay the edge mostly disappears (-0.03 to +0.02; best cell +0.04 to +0.05, ~1.7 SE). The apparent edge is stale quotes versus a faster reference price, not a better forecast.

## 7. Conclusions
1. No strategy tested has a reliable, cost-adjusted positive EV on the current 15 s snapshots.
2. The only candidate: late entry (<= 150 s, ask >= 0.98), EV +0.2 to +0.7 c per contract, high tail risk, needs depth/fill checks.
3. The model-based "stale quote" edge, if real, depends on fill speed. It cannot be proven with 15 s data.

## 7b. Gap rule: when to enter and how big the gap must be (`src/gap_rule.py`, `python run.py gap`)
`pct = 100*ln(reference_price/floor_strike)`; pct > 0 means YES leads, pct < 0 means NO. Per time-to-close bin, the smallest |pct| for which the
Wilson 95% lower bound of the leader's win rate is >= 0.95 (one observation per market per bin, all markets):

| Seconds to close | Min \|pct\| (%) |
|---|---|
| 15-60 | 0.01 |
| 60-120 | 0.04 |
| 120-180 | 0.10 |
| 180-240 | 0.22 |
| 240-600 | none (no gap size reached 95%) |

So the meaningful window is the last ~4 minutes; the earlier it is, the larger the gap must be. Exported as `outputs/simulated/gap_rule.json`.
Replay (thresholds fit on dev, applied to test, fee + $0.01 slip, one entry per market): target 0.90 -> n=515, win 90.1%, EV -0.000 +- 0.013;
target 0.95 -> n=145, win 92.4%, EV -0.007 +- 0.023; with a 15 s fill delay EV drops to -0.03 to -0.05. The all-data thresholds above are in-sample;
dev-only thresholds are stricter (0.03% at 15-60 s, 0.06% at 60-120 s, none earlier) because dev has only 333 markets.
Win rate stays ~= the ask price, so this rule picks safe entries but does not by itself create positive EV; its value is a clear trigger for small size.

## 8. Proposed prod integration (shadow mode first)
Nothing in this repo calls a trading API or the live bot. To move this toward prod, in the bot repo (kalshi-trading-bot):
1. Compute the features above from the live reference-price/strike feed at each decision tick (same definitions, no look-ahead).
2. Score with the dev-fit logistic model (coefficients and feature order are in `outputs/simulated/pattern_logit_model.json`) and log `p_model`, bid/ask, and decision per tick. **Do not place orders yet.**
3. Log quote timestamps and the delay between reference-price update and book update, at 1-2 s resolution.
4. After a few hundred markets, re-run `python run.py model` on the new data (and compare against logged live fills/prices) before enabling orders.
5. If enabled: small size, entry only when edge >= margin 0.08-0.12 after fees and slippage on the live ask, max one entry per market, daily loss cap, kill switch.

Open items: refresh `reports/MOMENTUM_V2_ANALYSIS.md` and the `run.py check` expectations to the new data, collect higher-frequency quotes. The logistic coefficients are exported by `python run.py model` to `outputs/simulated/pattern_logit_model.json`.
