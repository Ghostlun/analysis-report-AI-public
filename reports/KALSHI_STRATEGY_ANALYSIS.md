# Kalshi KXBTC15M Strategy Analysis

Scope: read-only analysis of `AIRelated.ipynb` (original retained in `archive/AIRelated_original.ipynb`) and the local KXBTC15M research exports. Application source references were inspected separately and are not required to read this report.
File layout note: data is in `data\raw\`, shared code in `src\` (`kalshi_lib.py`, `kalshi_strats.py`), one-off scripts named below are in `experiments\` (run with `python run.py legacy <name>`).
No application code or trading settings were changed, no orders were placed, no live service or credential was accessed.

Labels used throughout: **[F]** observed fact, **[I]** inferred, **[A]** assumption.

## 1. Bottom line

* **No strategy shows a credible, fee-adjusted, execution-robust advantage.** Every ROI confidence interval on held-out data includes zero or collapses under a one-snapshot delay. Only 9 usable BRTI days (3 held-out days) and one market regime are available.
* The **current default (`five_minute_95cent_force_v1`) loses money** in both dev and validation after fees and the project's own +$0.01 slippage (validation ROI −1.96%, CI −5.4%…+1.2%). Its raw win rate (94–95%) is *below* the break-even win rate (95.4–95.8%).
* The notebook's "100% win rate at 15s before close" result is **not reproducible or tradable** (Section 3).
* Only one family is worth further **paper** validation, with low expectations: a **BTC-distance z-score filter** (buy the BTC-favoured side with ask ≤ $0.99 only when `|BRTI−strike| / (σ·√sec_left) ≥ 1.5`, entering 30–240/300 s before close). It was positive on held-out data at every quoted/slippage scenario but with margins of 1–4% on spend, 0 losses in 73–121 validation trades (so one loss changes the sign), and it was flat-to-negative on development data under delay. It is a hypothesis, not a finding.
* Earlier/lower-price entries (ask ≤0.70/0.80) are clearly negative after delay. Take-profit and time exits hurt; a BTC-flip stop is the only exit that helped under no-delay fills, and it fails under a 15 s delay.

## 2. Data audit

### 2.1 CSV `KXBTC15M_all.csv` [F]
| Item | Value |
|---|---|
| Rows / columns / tickers | 54,384 / 24 / 933 |
| Collection window (UTC) | 2026-10-16 13:29 → 2026-10-29 16:10 |
| Snapshot cadence | median gap 15.03 s; only 3 gaps > 45 s, 1 > 120 s |
| Duplicates | none (by `id` and by `(ticker, collected_at)`) |
| Rows after close (`sec_to_close < 0`) | present for 925 markets; **excluded** from all analysis |
| Last pre-close snapshot | ≈7 s (before Oct 22) to ≈15 s (from Oct 22) before close; no data in the last seconds |
| Order book | top-of-book only; `yes_ask + no_bid = 1` always. **No sizes/depth**. `volume_contracts` is cumulative |
| Missing asks | one-sided books: ~40% of rows at ≤20 s, ~22% at 30–60 s, ~8% at 60–120 s, ~0.3% at 120–300 s |
| BRTI reference (`reference_price_usd`, `btc_price_difference_usd`) | **missing entirely before 2026-10-21**; ~100% present afterwards (586 settled markets, Oct 21 03:15Z → Oct 29 16:00Z) |
| `cap_strike` | 100% null |
| Settlement | 487 NO / 445 YES / 1 missing; 21 are "determined" rather than "finalized". `official_settlement_result` equals `official_final_btc_price >= floor_strike` in 932/932 |
| Leakage | settlement columns are populated on **every** snapshot row; they must never be used as features |

Coverage of 15-minute slots is poor: only 933 of ~1,260 expected markets exist (e.g. 13 on Oct 21, 28 on Oct 24, 29 on Oct 25; 96 on full days).
Markets per UTC day: 10-16: 42, 10-17: 96, 10-18: 92, 10-19: 68, 10-20: 47, 10-21: 13, 10-22: 76, 10-23: 96, 10-24: 28, 10-25: 29, 10-26: 96, 10-27: 96, 10-28: 96, 10-29: 58.

### 2.2 Local project data [F]
(Read-only SQLite inspection.)
* `market_tracking.db`: 126 snapshots / 5 markets, **0 settlements, 0 paper orders**; decisions are only `model_not_validated` (13) and `too_close_to_close` (2).
* `demo/auto_trading.db`: all tables empty. No `production/auto_trading.db`.
* `production/manual_orders.db`: 27 intents (6 filled buys, 8 previewed buys, 3 rejected, 10 previewed sells) and 1 `order_fills` row. Five of six filled intents have null `avg_fill_price`/`fees_paid`. They are **manual** orders (Oct 20–21), not strategy orders; no exit was ever submitted.
* **Consequence:** there are no stored signals, fills, fees or settlement-linked P&L for any automated strategy. Everything below is a **simulation on snapshots [I]**. `docs\STRATEGY_COMPARISON_DESIGN.md` reaches the same conclusion.

## 3. Verification of the notebook

| Claim / code | Finding |
|---|---|
| Outputs consistent with code | **No.** Stored outputs show 930, 861, 645 and 518 markets in different cells. The strategy table with 100% win at `entry_time 15` comes from code that is not in the notebook (cell 7 is a HistGradientBoosting model that does not print it). |
| Cell 1 drops rows with null asks (6,827) | Survivorship bias near close: missing asks are ~40% at ≤20 s and are concentrated on one-sided (decided) books. |
| PnL in cells 10–15 | Excludes fees and slippage. |
| "Estimated outcome from last BTC price" (cell 16, n = 13) | Invalid as an outcome: the last BRTI reading (~15 s before close) disagrees with the official result in **14 of 586** settled markets (2.4%) because settlement uses an average. Use `official_settlement_result`. |
| Best entry at 15 s to close | In-sample grid winner with no validation split. Infeasible: nothing exists in the last ~7–15 s of data, asks are missing ~40% there, and the project forbids execution <20 s (`min_execution_seconds`). |
| Momentum functions (cells 17–21) | Only demonstrated on hand-picked numbers; never backtested. |

The headline high accuracy at short horizons with large distances is real **[F]** but already priced: in the distance ≥100 / ≤120 s bucket the ask is ≈0.99, leaving no edge after fees.

## 4. Fees and execution model

Sources: `backend/app/services/order_preview.py` (`taker_fee`, `_fee_estimate`), `paper_trading.py` (`_fee`, `plan_fill`, `spend_for`, `SLIPPAGE`), `core/config.py:106` (`order_preview_taker_fee_rate = 0.07`), `schemas/auto_trading.py:15-26` (defaults), `strategy_engine.py`, `paper_strategy.py`, `live_strategies.py`.

* Fee per fill = `ceil_6dp(0.07 × n × p × (1−p) × multiplier)`; multiplier defaults to 1. **[F from code]**. A real fill (4 @ 0.61) recorded 0.0667 vs formula 0.066612, suggesting exchange rounding up to 4 dp. **[I]** The multiplier for KXBTC15M could not be verified (no live access). **[A]** =1.
* Total debit rounded up to $0.01; whole contracts; `plan_fill` prices at ask + $0.01 slippage (cap 0.99) and takes the larger of the fee at slipped and quoted price; no fee at settlement. **[F]**
* Max total spend $5 including fees: contracts = largest n with `n × price + fee ≤ 5` (`kalshi_lib.size_buy`). At ask 0.95 that is 5 contracts, so the $ at risk per trade is tiny and each trade has a ~$0.2 fee drag.
* Sells use the same fee formula on the executable bid, minus $0.01 slippage **[A]**.
* Each market gets one entry per strategy; entries need ≥20 s remaining.

Scenarios (`kalshi_lib.SCEN`):
| ID | Meaning |
|---|---|
| S0 | quoted ask, no slippage (optimistic) |
| S1 | project default: ask + $0.01 |
| S2 | order lands one snapshot (~15 s) later at that snapshot's ask + $0.01, with a limit of decision ask + $0.01; if the quote moved further the trade is **missed** |
| S3 | as S2 but +$0.03 slippage |
| S4 | thin book: only 3 contracts fillable |

Depth is unknown, so S4 is an assumption, not an observation.

## 5. Method

1. Outcome = official settlement only. Markets without a result (1) are excluded.
2. Features use only data at or before the decision snapshot (BRTI−strike distance, 60 s ask/price direction stability "stable60", 60 s BTC move "move60", z-score).
3. Chronological split, day-aligned, entire markets per set: **development = markets closing before 2026-10-27 00:00Z** (337 BRTI markets, Oct 21–26, six days) and **validation = Oct 27–29** (249 markets, three days). Strategies needing BRTI use only these 586 markets.
4. The grid was explored on development data only (≈100 combinations: time window {90…300 s}, max ask {0.80…0.99}, min distance {0…100 USD}, stable on/off; then z-score and move filters). σ for the z-score was estimated on development only (≈$4.28/√s ⇒ ≈$128 15-minute std).
5. Validation was run once per chosen candidate and its neighbours, **without retuning**. Bootstrap (2,000 resamples of trades) gives ROI CIs; this ignores intra-day correlation so the CIs are, if anything, too narrow.
6. Daily results, drawdown (peak-to-trough of cumulative net) and losing streaks are on the chronological trade list.

## 6. Results

ROI = net P&L / total spent including fees. BE = average per-contract cost including fees = win probability needed to break even. "Win" = side in the money at settlement. 95% CI is for ROI.

### 6.1 Baselines (project strategies replayed on snapshots)
S1 (project assumptions). Dev: 337 markets, Val: 249 markets.

| Strategy | Split | Trades | Win | BE | Net $ | ROI | ROI 95% CI | Max DD $ | Longest losing streak |
|---|---|---|---|---|---|---|---|---|---|
| **95force (default)** | dev | 334 | 94.9% | 95.8% | −15.47 | −0.95% | −3.4…+1.4 | 22.4 | 2 |
| | val | 249 | 94.0% | 95.4% | −23.69 | −1.96% | −5.4…+1.2 | 30.8 | 1 |
| price_threshold_v1 | dev | 333 | 93.4% | 93.7% | +18.61 | +1.18% | −2.6…+5.0 | 21.3 | 2 |
| | val | 249 | 93.2% | 93.7% | +10.35 | +0.87% | −3.2…+5.0 | 22.0 | 3 |
| momentum_v1 | dev | 327 | 95.1% | 96.1% | −16.49 | −1.05% | −3.7…+1.2 | 30.8 | 1 |
| | val | 245 | 95.5% | 96.1% | −6.76 | −0.57% | −3.5…+2.0 | 18.6 | 2 |
| direction_v1 | dev | 334 | 79.6% | 82.9% | −62.29 | −3.97% | −9.4…+1.4 | 114.1 | 4 |
| | val | 249 | 79.9% | 83.1% | −36.95 | −3.17% | −9.8…+3.7 | 50.1 | 3 |

Sensitivity (net ROI, val): 95force S0 −0.99%, S2 −4.57% (63% coverage), S3 −3.79%; price_threshold S0 +1.94%, S2 −0.97% (58% coverage), S3 −3.59%; momentum S0 +0.34%, S2 −0.14%, S3 −1.69%; direction S2 −7.22%.
Validation daily net, 95force: Oct 27 −29.66, Oct 28 −0.19, Oct 29 +6.16; price_threshold: +6.01 / +1.70 / +2.64.

Reading: the apparent "positive" price_threshold result is ~1% on spend with a CI spanning −3%…+5%, turns negative under any delay, and is within noise. Strategies with 94–95% win rates lose because the break-even win rate after the $0.01 slippage plus fees is higher than the realised win rate. High win rate is not an edge.

### 6.2 Candidate entry conditions
Entries use the BTC-favoured side (sign of BRTI − strike) unless noted. S1 ROI, then S2 and S3 ROI where informative. "t≤X" = first qualifying snapshot with 30 s ≤ sec_left ≤ X.

| Candidate (chosen on dev) | Dev trades / ROI (S1) | Val trades / ROI (S1) | Val S2 | Val S3 | Verdict |
|---|---|---|---|---|---|
| C1: t≤120, ask≤0.90, stable | 97 / +3.5% | 81 / **−8.8%** | −28.5% | −23.8% | **Overfit** – dev winner, validation loss |
| C1 neighbours: t≤120 ask≤0.95; t≤180 ask≤0.90 | +2.3%; −4.0% | −7.1%; +0.5% | −21%; −1.4% | −16.6%; −5.3% | inconsistent |
| C2: t≤180, ask≤0.90, move60≥0, stable | 101 / +8.9% (CI −3.0…+20.1) | 83 / +6.5% (CI −5.6…+17.6) | +2.7% (n=37) | −1.5% | Promising-looking, but CI spans 0, only 33% coverage, flips negative in S3 and dev S2 |
| C2 neighbours: ask≤0.99 | 224 / +4.4% | 157 / +1.9% | +0.1% | −3.7% | shrinks to noise |
| C2 neighbours: t≤120 ask≤0.90 | 50 / +12.4% | 39 / +0.2% | −24.6% | −23.7% | **Unstable** (the dev "best") |
| **C3: z≥1.5, ask≤0.99, t≤240** | 151 / +1.3% | 96 / **+2.9%** (CI −0.4…+6.1) | +1.3% (n=65) | −0.1% | **Most consistent**, but thin |
| C3 neighbours: z≥1.5, t≤180 | 119 / +1.0% | 73 / +4.5% (0 losses) | +1.5% | +1.2% | same direction |
| C3 neighbours: z≥1.5, t≤300 | 180 / +0.9% | 121 / +3.3% (CI +0.7…+6.0) | +1.3% | +0.3% | same direction |
| z≥1.0 / z≥2.0 (ask≤0.99, t≤180/300) | dev ≈ 0.1% … −0.5% | +1.2%…+3.7% | mixed | mixed | neighbours positive on val, ≈0 on dev |
| Early/low price: BTC side, ask≤0.70, t≤300 | 163 / +1.4% | 117 / +0.4% | **−21.6%** | −23.8% | Negative once a delay is allowed; drawdown $91 on ~$300 spend |
| Early/low price: ask≤0.80 | 201 / −2.6% | 141 / −0.6% | −17.8% | −12.6% | Negative |

C3 detail (S1, val): 96 trades, win 99.0%, BE 96.8%, net +$13.67, max DD $4.77, longest losing streak 1, 3/3 days positive; dev 151 trades, win 98.0%, BE 97.0%, net +$9.57, DD $8.71, 6/6 days positive. Under S2 dev ROI is −0.3%; under S3 −1.1% (dev), −0.1% (val). Its edge per trade is ≈ $0.03–0.14, about the size of the fee/slippage uncertainty.
With only three held-out days and 96 trades at a 99% win rate, one or two losing markets would erase the gain. The dev-vs-val improvement (1.3% → 2.9%) is as consistent with luck as with a real effect.

### 6.3 Exits (price_threshold_v1 entries; S1 unless noted; no depth, executable bid, bid − $0.01 slippage, fees included) [estimates]

| Exit | Dev ROI | Val ROI | Val ROI under S2 |
|---|---|---|---|
| Hold to settlement | +1.18% | +0.87% | −0.97% |
| Take-profit at bid ≥0.97 | −0.32% | −1.62% | −3.67% |
| Take-profit at bid ≥0.99 | −0.18% | −0.78% | −2.41% |
| Stop: bid fell 0.20 from entry | +1.27% | +1.63% | −0.10% |
| Stop: bid fell 0.35 | +1.37% | +0.89% | +0.65% |
| Exit when BTC flips to wrong side of strike | **+3.51%** | **+2.59%** | −0.94% |
| Same, flip by ≥$10 | +2.24% | +1.37% | −0.43% |
| Time exit at ≤90 s / ≤45 s | −0.42% / −0.62% | −1.55% / −1.48% | −3.53% / −1.39% |

* Take-profit and time exits give away the fee-free settlement payout and pay a second fee + slippage: worse in every case.
* A BTC-flip exit improved both splits at 15 s resolution without delay, but this relies on selling at the quoted bid immediately; with a 15 s delay the benefit disappears. Intra-15 s moves and bid depth are invisible. Treat as an **estimate** to test with real exit logging only.

### 6.4 Coverage and independence
* Only **9 days** with BRTI data (6 dev, 3 val); one BTC regime; trades within a day are correlated (market-wide BTC trend), so effective independent samples are far fewer than the trade counts.
* Candidates fill only 15–60% of markets; baselines ~99%.
* A priced-in market: calibration bucket analysis (586 markets, 30–300 s) shows win rate ≈ ask in each bucket (mean edge −1.2% in the 0.90–0.95 bucket before fees). The only bucket suggesting positive edge (BTC-favoured side priced ≤0.50, +12 pts) rests on a small number of independent markets.

## 7. Conclusion

**What the data supports.** The market is close to efficiently priced at the 15 s snapshot level. After the fee `0.07·p·(1−p)` and a $0.01 slippage, buying near-certain outcomes (ask ≥0.90) needs a ≥93–97% win rate to break even; the baselines land at or just under break-even. 2.4% of markets also finish opposite the last BRTI reading, which caps the usefulness of "obvious" late BTC distance.

**Most consistent on held-out data.** The z-score-gated entry (C3, z≈1.5, any t≤180–300 s) was the only family with a positive held-out ROI across S0/S1/S2/S4 and several neighbours and with a short drawdown; it is still below statistical significance, almost flat under S3, and dev-delay ROI is slightly negative. **Hence: no demonstrated credible advantage.** Next in line is C2 (distance with non-negative 60 s BTC move), whose neighbours are unstable.

**Candidate rules for paper testing (hypotheses, fixed in advance; do not retune)**
* *Entry (C3):* 30 s ≤ seconds-to-close ≤ 240 s; side = BRTI vs strike; require `|BRTI−strike| ≥ 1.5 × $4.3 × √seconds_left`; BTC-favoured side ask ≤ $0.99; one entry; whole contracts within $5 including fee.
* *Skip:* ask missing/one-sided book; BRTI stale or absent; <30 s remaining (20 s minimum plus one polling cycle); any market where the snapshot ask is >$0.01 above the signal-time ask (limit-price rule).
* *Exit:* hold to settlement as the base. Test a BTC-flip stop as a separate arm only if real bid/depth logging is added. Do not use take-profit or late time exits.
* *Comparison arm:* run `five_minute_95cent_force_v1` unchanged in parallel; C3 trades less (≈40–50% of markets), has no forced low-edge entry in the last 60 s, and had a shallower drawdown (≈$5 vs ≈$31 on val); C3's edge versus the default on held-out data was ≈ +4.9 pp ROI (+2.9% vs −2.0%) but that gap is within noise.

**Additional data needed before a stronger recommendation**
* ≥ 30–60 independent days with BRTI on every market, including trending, volatile and quiet regimes; full collector coverage (≈ 74% of slots are present now).
* Order-book depth and sizes at decision time, tick-level or ≤ 1 s data near the close, and logs of un-throttled decisions.
* Actual paper/live orders, fills (price, quantity, fee), and official settlements linked to each signal; confirmed fee multiplier and the real rounding rule.
* Verified settlement lag and use of 60-second average (BRTI) as the official final price.

## 8. Reporting proposals (minimum fields)
Builds on the existing proposal in `docs/STRATEGY_COMPARISON_DESIGN.md` (`/api/strategy-comparison/{trades,summary,coverage,strategies,trades/{id}}`).

**Per trade (API + live table):** `strategy_id`, `strategy_version`, `config_hash`, `market_ticker`, `side`, `signal_time`, `decision_snapshot_id`, `seconds_to_close_at_signal`, `signal_ask`, `signal_bid`, `target_price`, `reference_price`, `distance_usd`, `z_score`, `move60`, `stable60`, `predicted_fill_price` (= ask + slippage), `predicted_fee`, `predicted_quantity`, `submit_time`, `actual_fill_time`, `actual_fill_price`, `actual_quantity`, `actual_fee`, `fill_latency_ms`, `slippage_vs_signal`, `skip_reason` (fixed enum: no_signal, one_sided_book, stale_ref, too_close, limit_exceeded, insufficient_balance, zero_quantity), `exit_reason`, `exit_time`, `exit_price`, `exit_fee`, `official_result`, `settlement_time`, `settlement_status` (pending/determined/finalized/missing), `net_pnl`, `pnl_is_estimated`, `data_flags`.

**Per strategy summary / report:** eligible markets, trades, skips by reason, coverage; win rate and break-even win rate; net P&L, spend, ROI with CI; max drawdown, longest losing streak, daily P&L; dev vs validation split flag; mean (predicted − actual) fill price and fee; share of settlements pending/missing; days observed.

**Live table:** current strategy, markets seen, signals, fills, open positions, today's net P&L, and the predicted-vs-actual fill gap. Also store the raw top-of-book (and depth when available) at each decision for replay.

## 9. Reproduction
Python 3.11+ with pandas, NumPy and SciPy. Project-relative reproduction files:
* `src/kalshi_lib.py` – loading (pre-close rows only), features, fee/sizing, fill scenarios, summaries.
* `src/kalshi_strats.py` – baseline replays, grid rule factory, exit rules.
* `experiments/make_report_tables.py` – prints the main comparison tables.
* Seed 7, 2,000 bootstrap resamples; split boundary 2026-10-27 00:00Z.

Project source references: `strategy_engine.py` (rules), `paper_strategy.py` (95force tick ≈795–965; momentum ≈967–1255; `_enter`), `paper_trading.py` (fee/plan_fill), `order_preview.py` (fee), `live_strategies.py` (registry), `core/config.py`, `schemas/auto_trading.py`.

## 10. Assumptions and limitations
* Snapshot replay at 15 s cadence: real decision timing, partial fills, queueing and cancellations are not observed. Market quotes between snapshots are invisible.
* No depth: S4 (3 contracts) is a guess; $5 trades are small so the effect is modest but unverified.
* Fee multiplier and sell-side fee assumed equal to the buy formula.
* The Oct 16–20 markets lack BRTI and were excluded from BTC-dependent strategies.
* Replayed baselines approximate the project's behaviour (momentum projection and forced phase simplified to snapshot values); they were not validated against recorded decisions because none exist.
* Candidate thresholds (z=1.5, σ) come from ≈100 explored dev combinations; some selection bias remains even with held-out testing, and the validation set has only three days and zero or one losing trade in the best candidates.
* One market regime (Oct 21–29); results should not be extrapolated.

## 11. Addendum: follow-up questions (scripts in the same folder)

* **Target price** (`strike_check.py`): `floor_strike` equals the previous market's official final price in 923/923 consecutive markets. Markets open near the strike (first-snapshot YES ask mean 0.504), so early direction is ~50/50. YES share 47.7%.
* **Continuity between markets** (`continuity_check.py`): corr(previous move, current move) = −0.03; same-direction rate 48.8%. Previous result is not usable as a signal.
* **Leader persistence and distance** (`hold_by_time.py`, `dist_stability.py`): BTC-side agrees with the official result 77% at 7 min, 86% at 3 min, 90% at 2 min, 97% at 1 min before close. Stable (≥95%) needs roughly $150 at 5–7 min, $100 at 3–4 min, $50–75 at 2–3 min, $25 at <1 min. These prices are already ≈0.95–0.99.
* **Momentum losses** (`momentum_losses.py`): 27/572 losses (4.7%); 78% came from the 0.90–0.95 momentum path (7.8% loss rate vs 2.0% for ask ≥0.95); 20/27 had z < 1.5.
* **Entry at ≈0.85 vs waiting for 0.95** (`entry085_vs_095.py`, `zscore_low_price.py`, `band085_095.py`): no stable edge inside ask 0.85–0.95, even with distance/z filters; high-distance cells have 3–11 trades.
* **Buy near 0.50 and ping-pong** (`pingpong_050.py`): direction-less entry −13% ROI; take-profit/stop exits worsen it. BTC-favoured side held to settlement: +9.4% ROI (CI −2.8…+21.9), unconfirmed.
* **Model-probability edge** (`model_edge.py`, `model_edge_checks.py`): buy the BTC-favoured side at any ask when `Φ(dist/(σ√sec)) − cost ≥ margin` (σ = $4.275/√s from dev data, 30–300 s, hold to settlement). S1 ROI: margin 0.04 → dev +43% (100 trades), val +45% (78); margins 0–0.10 and a Student-t variant are all positive on both splits; 8 of 9 days positive. **Not credible yet:** under a 15 s delay only 27 of 178 trades remain fillable and ROI is −15% (quotes move once the edge appears: adverse selection); a 3-contract depth cap cuts ROI to +24%; top-of-book size and quote freshness are unobservable in this CSV (`source_timestamp` is the market open time, not a quote time). Next step is paper validation logging signal-time quote, order time, actual fill price/quantity and latency (Section 8 fields) plus book depth.
