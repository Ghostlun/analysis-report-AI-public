# five_minute_momentum_v1: loss analysis and v2 plan

Analysis only. No strategy code, live setting or order was touched. Reproduce the frozen study with `python run.py actual`, `python run.py simulated`, `python run.py filters`, and `python run.py check` using the matching local exports (`data/raw/live_orders_all.csv` and `data/raw/KXBTC15M_all.csv`). Generated tables are written under `outputs/`; analysis code is in `src/momentum.py`.
Labels: **[F]** fact from data/code, **[I]** inference, **[H]** hypothesis, **[M]** missing evidence.

> **Correction to my earlier answer.** I previously analysed all 307 rows together. They contain three strategies; only 191 rows are `five_minute_momentum_v1`. The conclusions below replace the earlier per-mode figures (e.g. `threshold_normal` belongs to `price_threshold_v1`, not momentum).

## 1. Bottom line

* **[F]** Momentum v1 live: 146 settled trades, 138 wins / 8 losses, **net −$6.03** after $2.94 fees (Oct 28 00:10 UTC → Oct 30 16:30 UTC). Wins +$38.40, losses −$44.44. Oct 28 +$4.12, Oct 29 +$5.65, Oct 30 −$15.80.
* **[F]** The win rate (94.5%) is about equal to the average price paid (94.1%) and fees are ~0.3¢/contract, so v1 has no measurable edge. It earns a few cents per win and loses ~$4–8 per loss.
* **[I]** The losses are mostly *valid signals that lost*: BRTI was on the signal side, the ask was high, then BTC reversed. The common feature is that **the price paid exceeded what BTC's distance from strike justified** (low time-adjusted distance, z < 1.5). v1 never looks at distance, only at the ask.
* **[F]** Two losses (#185, #210) have fills that are inconsistent with the signal rules (filled at $0.85 and $0.14 although the rule needs an ask ≥ $0.90). They are unexplained without decision logs.
* **[F]** A replay of v1 over all 686 markets with BRTI data (Oct 21–30) is flat-to-negative: −$13.6 (Oct 21–26) and −$20.0 (Oct 27–30) at N=5 contracts with +$0.01 slippage. 95% intervals include zero.
* **v2 candidate:** drop the early-momentum branch, buy only when the time-adjusted distance is large (z ≥ 1.5 to 2) and the ask is not already above ~$0.97–0.98. On the untouched later period it was ≈ breakeven to modestly positive with slippage, and beat v1 by about +$20 (paired 95% interval −$13 … +$59), **but every interval includes zero**. It is a hypothesis for shadow testing, not a proven improvement.

## 2. Data verification

| Item | Finding |
|---|---|
| File | `data\raw\live_orders_2026-10-30.csv`, 307 rows × 23 columns |
| Time zone | All timestamps are UTC (`+00:00`). Tickers encode the **close time in US Eastern** (EDT, UTC−4): `KXBTC15M-26OCT301230-30` closes 12:30 ET = 16:30 UTC. Market snapshots are UTC. |
| Strategies | `five_minute_95cent_force_v1` 50 rows (Oct 25–26), `price_threshold_v1` 66 (Oct 26–27), **`five_minute_momentum_v1` 191 (Oct 28 00:10 → Oct 30 16:41)** |
| Momentum status | 146 settled, 18 canceled (IOC unfilled, 0 contracts), 27 rejected (21 `quote_moved`, 6 `not_found_after_reconciliation`, 1 `order_not_found_at_exchange`) |
| Entry modes | `momentum_standard` 108 intents (89 filled), `momentum_early` 83 (57 filled) |
| Partial fills | 1: id 171, 0.02 of 5 contracts at $0.97 (a ~$0.02 position). Every other filled order is full. |
| Duplicates | none: 0 repeated tickers, 0 repeated `client_order_id`, 0 repeated exchange ids. One order per market per run is enforced by `UNIQUE(run_id, market_ticker)` (`auto_trading_store.py:53`) and `market_has_claim` (`auto_trading.py:432`). |
| P&L reconciliation | For all 146: `realized_pnl = payout − fill_cost − fees` to 4e-16. `fees_usd` matches `0.07·n·p·(1−p)` (e.g. 8 × 0.953 → $0.0251). Net −$6.0343; fees $2.9403; cost $765.11. |
| Market data | `KXBTC15M_all.csv`: 60,195 rows, 1,032 tickers through 2026-10-30 16:52 UTC, 15 s snapshots. BRTI (`reference_price_usd`) exists only from Oct 21, giving **686 settled markets with BRTI**. All 146 traded tickers are present. |
| Fill size | 4–5 contracts to Oct 29 21:xx UTC, 7–8 from Oct 30 02:xx UTC, consistent with the budget change in commit `f583edd` ("Setup 100 max", Oct 29 22:29 ET). Oct 30's 4 losses were ~60% larger than Oct 28–29's. |

**[M] Decision logs are not available.** `backend\data\trading\production\` has no `auto_trading.db`; `demo\auto_trading.db` is empty. The strategy writes per-tick decisions with `executable_ask_usd`, slopes, BRTI, `brti_age_seconds` and latencies (`auto_trading.py:462-545`), but none of that was supplied. Everything "known at entry" below is **reconstructed from the 15 s collector snapshots** (last snapshot before `intended_at`, median age 4.1 s, max 14.6 s).

## 3. What the code actually did (HEAD `44066fb`; strategy files have no uncommitted diff)

Momentum was added in `c1242d7` (Oct 26). `089f931` (Oct 27 23:30 ET = Oct 28 03:30 UTC, 3 h after the first momentum order) changed scheduling and risk gating; nothing in the signal rules changed after Oct 26.

| Step | Rule | Source |
|---|---|---|
| Cadence | Every 15 s; since `089f931` aligned to UTC :00/:15/:30/:45 | `auto_trading.py:42-48, 140-142, 349-356` |
| Window | Evaluate only when 300 ≥ seconds-left; direction expires at `<20 s` | `live_strategies.py:13-14`, `auto_trading.py:427-429`, `strategy_engine.py:50-70` |
| Direction | BRTI vs strike; BRTI > strike → YES, < → NO, tie/missing → wait. **No minimum distance.** | `strategy_engine.py:42-48`, `auto_trading.py:504-508` |
| Quote freshness | Skips only if the quote fetch itself warns "stale" (took too long). BRTI age is logged, not gated for momentum. | `auto_trading.py:445-448`; `order_preview.py:239,265` |
| Ask used | Cheapest level in the live order book for the chosen side (`parse_asks`) | `auto_trading.py:519-521` |
| Standard entry | Ask ≥ $0.95 → BUY | `paper_strategy.py:1026-1028` |
| Early entry | $0.90 ≤ ask < $0.95 **and** 30 s and 60 s slopes both > 0, 30 s slope ≥ 0.8 × 60 s slope, projected time to reach $0.95 ≤ min(60 s, time left). History = collector snapshots + own samples; references must be within 20 s of look-back. | `paper_strategy.py:957-965, 1029-1070`; `auto_trading.py:395-411` |
| Below $0.90 | Wait and retry next tick | `paper_strategy.py:1029` |
| Sizing | Budget per market (default $5, cap $100) → max affordable contracts | `schemas/auto_trading.py:18`, `live_strategies.py:17` |
| Order | Preview then submit IOC buy; limit = **last swept ask + $0.01**, rounded up | `auto_trading.py:553-558`, `manual_trading.py:171-185` |
| Slippage / retries | At submit, if best ask > limit: `quote_moved` reject (21 cases). Rejects are `retryable` → a later tick may try again until the window ends. | `manual_trading.py:1044`, `auto_trading.py:557-565` |
| Duplicate protection | One claim per (run, market) in SQLite plus `_finished_markets` | `auto_trading_store.py:53, 291-345`; `auto_trading.py:432-434` |
| Exit | None; hold to settlement | `live_strategies.py:20` |
| Risk limits | Since `089f931`, momentum is in `CONFIGURED_RISK_EXEMPT_STRATEGIES`: **daily-loss, daily-spend, trade-count and exposure limits are not enforced**; only available balance gates an order | `live_strategies.py:15`, `auto_trading.py:578-596` |

Active rules per trade: all Oct 28–30 trades ran the code above (the three-hour window before `089f931` used the older scheduler and the loss/spend limits; this cannot be separated without logs, **[M]**).

## 4. Fidelity of my replay

I replayed v1 on the 15 s snapshots (same direction, 0.95/0.90 thresholds, slope tests, window, one entry per market). Restricted to the Oct 28+ markets: **replay entered 247, live filled 146, 145 in common**; same side 99%, same mode 79%, mean |price difference| 2.1¢. The replay-only 102 are markets when the live runner was off or the order did not fill. **[I]** The replay is a reasonable approximation but not exact: snapshots are 15 s apart and miss intra-interval spikes, and live fills averaged 1.5¢ above the last snapshot ask (median 0.65¢, p90 5¢). Depth is not in the data, so fills are modelled at top-of-book. Fees use `0.07·p·(1−p)` per contract.

## 5. The 8 losing momentum trades

All timestamps UTC; "time left" is at `intended_at`; fees are in $. Win-needed = price + fee.

| id | Ticker (closes) | Entry | Left | Side | Mode | Fill | Qty | Fees | P&L |
|---|---|---|---|---|---|---|---|---|---|
| 164 | …281100-00 (Oct 28 15:00) | 14:55:19 | 281 s | NO | early | 0.920 | 5 | 0.0258 | −4.626 |
| 185 | …281645-45 (Oct 28 20:45) | 20:42:34 | 146 s | YES | standard | 0.850 | 5 | 0.0447 | −4.295 |
| 210 | …290015-15 (Oct 29 04:15) | 04:14:19 | 41 s | NO | standard | 0.140 | 5 | 0.0422 | −0.742 |
| 231 | …290830-30 (Oct 29 12:30) | 12:27:49 | 131 s | NO | early | 0.913 | 5 | 0.0279 | −4.593 |
| 270 | …300230-30 (Oct 30 06:30) | 06:26:02 | 237 s | NO | early | 0.923 | 8 | 0.0398 | −7.424 |
| 283 | …300545-45 (Oct 30 09:45) | 09:44:02 | 58 s | YES | standard | 0.956 | 8 | 0.0237 | −7.671 |
| 297 | …301000-00 (Oct 30 14:00) | 13:55:47 | 252 s | NO | early | 0.925 | 8 | 0.0389 | −7.439 |
| 306 | …301230-30 (Oct 30 16:30) | 16:27:17 | 163 s | NO | standard | 0.953 | 8 | 0.0251 | −7.649 |

What the strategy could see, reconstructed from the snapshot before entry (**[I]** approximate, 2–4 s old). `dist` = BTC (BRTI) distance from strike in the signal's favour; σ15 = std of 15 s BRTI changes over the last ~5 min; **z = dist / (σ15·√(time-left/15))**; Φ(z) = Gaussian chance the side stays correct; spread = ask − bid of the signal side; "worst after" = the most adverse signed distance in later snapshots (negative = BRTI crossed the strike against the trade); final = last BRTI snapshot's signed distance; official = settlement price vs strike.

| id | dist $ | σ15 $ | z | Φ(z) | Price paid | persist (snaps) | 60 s move in favour $ | 5-min range $ | spread | worst after $ | final $ | official vs strike | Class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 164 | 75.6 | 12.0 | 1.45 | 0.926 | 0.920 | 16 | +28.7 | 151 | 0.01 | −27.7 | −27.7 | 80,467.9 vs 80,454.0 | valid signal, reversal; paid ≈ fair |
| 185 | 30.0 | 14.3 | 0.66 | 0.746 | 0.850 | 3 | +22.2 | 122 | 0.00 | −9.3 | +10.8 | 81,020.2 vs 81,023.0 | weak setup; **fill/rule mismatch**; lost on settlement averaging |
| 210 | 0.8 | 7.9 | 0.06 | 0.524 | 0.140 | 4 | +4.6 | 50 | 0.01 | −21.7 | −20.4 | 79,752.6 vs 79,741.3 | **anomaly**: near-coin-flip, fill 0.14 |
| 231 | 29.8 | 7.7 | 1.29 | 0.901 | 0.913 | 8 | +18.9 | 57 | 0.01 | −33.2 | −25.5 | 80,011.8 vs 79,990.9 | valid signal, reversal; paid > fair |
| 270 | 81.9 | 15.4 | 1.33 | 0.908 | 0.923 | 15 | +41.3 | 101 | 0.00 | −55.0 | −53.6 | 78,520.0 vs 78,481.1 | valid signal, large reversal; paid > fair |
| 283 | 35.4 | 11.1 | 1.60 | 0.945 | 0.956 | 5 | +28.7 | 100 | 0.00 | −28.0 | −9.1 | 77,611.3 vs 77,613.9 | valid signal; $2.6 miss at settlement |
| 297 | 216.6 | 55.0 | 0.96 | 0.830 | 0.925 | 33 | +134.4 | 340 | 0.00 | −212.4 | −169.8 | 76,948.4 vs 76,839.7 | extreme-volatility regime; paid ≫ fair |
| 306 | 134.6 | 27.4 | 1.48 | 0.931 | 0.953 | 25 | +71.9 | 173 | 0.00 | −30.5 | −8.7 | 77,480.2 vs 77,467.9 | valid signal, reversal of ~$200 in 60 s; paid > fair |

Per trade, in order of evidence strength:

* **164, 231, 270, 306 [F/I]** – direction persisted and spreads were tight (no stale/wide quote). The strategy did exactly what it is built to do. Price paid was equal to or 1–2¢ above the Gaussian-implied probability, i.e. no edge to absorb a normal reversal. Not implementation errors.
* **283 [F/I]** – z 1.60, standard entry at 58 s. BTC fell back to the strike only at the end; the last BRTI print was $9 on the wrong side and the official settlement price ended $2.6 on the wrong side. Valid signal lost on a thin margin.
* **297 [F/I]** – σ15 = $55 and a $340 five-minute range: the highest-volatility market in the sample. A $216 distance is only z = 0.96, yet the ask was $0.925. v1 sees only the ask.
* **185 [F]/[H]** – z = 0.66, direction had held only 3 snapshots, and the filled price ($0.85) is 11¢ **below** the 0.961 snapshot ask 4 s earlier. The standard rule needs the live book's best ask ≥ 0.95. Possible causes **[H]**: the book moved sharply between the evaluation read and the IOC fill (the same market swung 0.67 → 0.96 → 0.73 inside three snapshots), or the evaluated and filled books differ. **[M]** requires `executable_ask_usd`, preview limit and fill levels.
* **210 [F]/[H]** – BRTI was $0.81 below strike (z = 0.06), the NO ask in the snapshot was 0.84 (below the 0.90 minimum), yet the order filled at 0.14. Either the signal ask was momentarily ≥ 0.95 and fell, or the preview/quote came from a different book than the snapshot. Unresolvable without logs. It also cost only $0.74, but it shows the entry can fill far from the price that triggered it. It is an **execution/consistency issue to investigate**, not a valid signal.

Other facts:

* 7 of 8 losses had z < 1.6; 5 of 8 had z < 1.35. 138 winners had median z 1.54 (p25 1.22).
* All 8 losses saw BRTI cross the strike at some later snapshot. 5 of the 138 winners also crossed back.
* The 15 s collector never saw a spread above 1¢ on these trades, so wide-spread/stale-quote is not the explanation. **[M]** The quote age at the actual order time is unknown.
* **Adverse selection [H]:** the 45 unfilled momentum intents (18 canceled, 27 rejected) would have won **44 of 45** (97.8%) versus 94.5% for fills. Orders fail to fill when price keeps rising (`quote_moved`) and fill when price is flat or falling. With 8 vs 1 losses, Fisher p ≈ 0.4; not significant.

## 6. Failure patterns

### 6.1 Price paid versus distance (z) — the main pattern **[F in-sample, I for cause]**

Live fills, by z, using the snapshot-reconstructed z:

| z | n | Φ(z) | Avg price paid | Win rate | P&L |
|---|---|---|---|---|---|
| 0–1.0 | 21 | 0.787 | 0.880 | 85.7% | −4.87 |
| 1.0–1.5 | 49 | 0.898 | 0.936 | 91.8% | −8.45 |
| 1.5–2.0 | 43 | 0.954 | 0.959 | 97.7% | +1.30 |
| > 2.0 | 33 | 0.990 | 0.963 | 100% | +5.99 |

Below z = 1.5 (70 trades) the price exceeded Φ(z) by 3–9¢ and the strategy lost $13.32 with 7 losses; at z ≥ 1.5 (76 trades) it made +$7.29 with 1 loss (Fisher p = 0.028, **post-hoc, selected after seeing the losses, not corrected for the many cuts examined**). Time-adjusted distance also separates what raw dollars cannot: distances of $30 and $216 were both z ≈ 1 because volatility differed 7×.

### 6.2 Price band

Fills in $0.90–$0.93: 22 trades, 4 losses, −$15.74. $0.93–$0.95: 24 trades, 0 losses. This is not stable evidence that a band is "bad": it is mostly early-momentum at low z (**[H]** same cause as 6.1).

### 6.3 Settlement is an average, not the last BRTI print

For 3 of 146 trades the sign of the last 15 s snapshot's distance disagreed with the official result: #185 lost although the last BRTI print was $10.8 in its favour, and 2 trades won although the last print was adverse. Entries with < $10–15 of cushion at the end are coin flips against the averaging window.

### 6.4 Size and gating

Oct 30 trades were ~8 contracts versus ~5 earlier, and momentum has no daily-loss gate (`live_strategies.py:15`). The same four Oct 30 losses at 5 contracts would have cost ≈ −$18.9 instead of −$30.2 (all 8 losses: ≈ −$33 instead of −$44).

## 7. v2 ideas (from the failure patterns; none assumed to be profitable)

1. **Time-adjusted distance gate (z).** Enter only if |BRTI − strike| / (σ15·√(sec_left/15)) ≥ z_min, σ15 over the last ~20 BRTI changes. Addresses 164/185/210/231/270/297/306. Evidence: §6.1.
2. **Edge check against the ask.** Equivalent form: require Φ(z) − ask − fee ≥ margin (e.g. 0.01–0.02). Normalises volatility regimes (297) and stops paying 0.95 for a 0.92 chance.
3. **Early-momentum branch off** (standard-only). In the replay the early branch is the persistent loser: dev 14 losses / 148 trades, −$21.6; test 12 / 162, −$7.9 (slip +$0.01). In the live data early is flat (−$0.06, 57 trades) and standard is −$5.98 (89), so **evidence is mixed**; treat as a shadow comparison, not a given.
4. **Fill-consistency guard.** Re-read the book at submit; abort if the side's best ask differs from the signal ask by more than ~0.03 or BRTI's side flipped. Addresses #185/#210 and the observed 0.09–0.7 fill-to-snapshot gaps (35 of 146 fills differed by > 3¢). **[H]** untestable on current data.
5. **Margin to the strike near close.** Require z to be met at the final 30–60 s as well, or avoid entries when the last BRTI is within ~$10–15 of the strike (settlement averaging).
6. **Risk controls independent of the strategy.** Restore daily-loss/exposure limits for momentum and size by fixed risk (e.g. 5 contracts), because 4 losses on Oct 30 cost $30.
7. **Not supported by the data:** a hard ask cap (≤0.97/0.98) alone — it lowered test P&L in the replay (§8); signal persistence ≥ 3 snapshots — test P&L −$20.5 (≈ v1), no discrimination (losses had persist 3–33 like the wins).

## 8. v1 vs v2 on identical historical opportunities

Method: all 686 markets with BRTI and an official settlement (Oct 21 03:06 → Oct 30 16:30 UTC), every 15 s snapshot as a decision point, one entry per market (first snapshot passing the rule), hold to settlement, **N = 5 contracts**, fee `0.07·p·(1−p)`/contract, three fill models: *ideal* (ask at the decision snapshot), *slip* (ask + $0.01, cap $0.99; matches live fills' +1.5¢ mean), *delay* (fill at the next 15 s snapshot only if its ask ≤ decision ask + $0.01, else no trade). Net P&L, drawdown in dollars at N = 5, 95% interval = bootstrap over trades (independence assumed; **[I]** optimistic).

Split: **development = markets that opened Oct 21–26 (339); untouched test = Oct 27–30 (347).** The grid (σ-gate z_min ∈ {0,1,1.5,2,2.5,3}, persistence ∈ {1–4}, ask cap ∈ {0.97,0.98,0.99,none}, standard-only or both) was scored on the development period only (slip model, ≥ 60 trades). The test period was then evaluated once for the chosen rule; other rules are shown as sensitivity, not selection.

**Chosen on development (pre-registered for test): standard-only, z ≥ 1.5, ask ≤ 0.97 (persistence had no effect).**

| Rule | Period | Fill model | Trades | Wins | Net P&L $ | 95% interval | Max DD $ |
|---|---|---|---|---|---|---|---|
| v1 | dev | ideal | 329 | 313 | +0.29 | −40.9 … +34.0 | 23.4 |
| v1 | dev | slip | 329 | 313 | −13.55 | −54.6 … +20.2 | 29.5 |
| v1 | dev | delay | 190 | 175 | −24.61 | −62.6 … +8.3 | 31.7 |
| v2 chosen | dev | ideal | 147 | 144 | +12.04 | −7.8 … +27.0 | 9.6 |
| v2 chosen | dev | slip | 147 | 144 | +5.17 | −14.7 … +20.1 | 10.5 |
| v2 chosen | dev | delay | 82 | 79 | +1.07 | −18.7 … +16.0 | 10.9 |
| **v1** | **test** | ideal | 342 | 324 | −5.80 | −48.4 … +32.9 | 15.9 |
| **v1** | **test** | slip | 342 | 324 | **−19.95** | −62.4 … +18.8 | 26.9 |
| **v1** | **test** | delay | 209 | 195 | −6.63 | −41.5 … +26.3 | 18.7 |
| **v2 chosen** | **test** | ideal | 145 | 141 | +6.90 | −13.7 … +22.5 | 8.0 |
| **v2 chosen** | **test** | slip | 145 | 141 | **+0.13** | −20.5 … +15.7 | 9.8 |
| **v2 chosen** | **test** | delay | 80 | 76 | −3.87 | −24.3 … +11.7 | 11.7 |

Paired difference on test (v2 − v1, slip): **+$20.08, 95% interval −$12.9 … +$58.8**. **Not statistically distinguishable from zero.** Roughly 58% fewer trades and 64% lower drawdown (9.8 vs 26.9) are the clearer effects; the P&L gain is dominated by avoiding v1's early-branch losses and low-z trades.

Sensitivity (slip +$0.01; dev | test; **post-hoc, not used for selection**):

| Variant | Dev trades / net | Test trades / net / max DD |
|---|---|---|
| v1 early branch only | 148 / −21.64 | 162 / −7.87 |
| v1 standard branch only | 181 / +8.09 | 180 / −12.08 |
| standard-only, z ≥ 1.5 (no cap) | 293 / +2.15 | 296 / +6.96 / 8.1 |
| standard-only, z ≥ 2 (no cap) | 260 / −1.00 | 256 / +8.74 / 6.2 |
| both modes, z ≥ 2 | 262 / −9.38 | 256 / +12.65 / 5.0 |
| ask cap ≤ 0.97 alone | 259 / −11.07 | 271 / −22.85 / 29.3 |
| persistence ≥ 3 alone | 325 / −14.92 | 341 / −20.46 / 27.1 |

Reading: **z-gating improved test P&L and drawdown in every variant** but the development period gave −$1 to +$5 for the same variants, so the effect is small and unstable; the ask cap and persistence by themselves did nothing useful. All intervals include zero. With ~3% losses, ±10 losses of noise decide the sign of every row; hundreds more trades per arm are needed for statistical resolution (≈ 1,000+ trades to detect a +1¢/trade edge).

### 8.1 What each filter does to trade count and P&L (SIMULATED; `python run.py filters`)

N = 5, slip +$0.01. `d_n`/`d_net` are versus v1 on the same markets. `skipped` = v1 trades on markets the rule no longer enters; `retimed` = same market entered at a different snapshot (e.g. a later one once the filter passes).

| Rule | Test n | Test losses | Test net $ | Test Δnet | Test max DD | Dev n | Dev net $ | Dev Δnet |
|---|---|---|---|---|---|---|---|---|
| v1 | 342 | 18 | −19.95 | – | 26.9 | 329 | −13.55 | – |
| only standard-only | 338 | 10 | −14.18 | +5.78 | 19.2 | 323 | +4.34 | +17.89 |
| only z ≥ 1.5 | 300 | 5 | +15.42 | +35.38 | 7.5 | 297 | −17.33 | −3.77 |
| only ask ≤ 0.97 | 271 | 18 | −22.85 | −2.89 | 29.3 | 259 | −11.07 | +2.49 |
| standard-only + z ≥ 1.5 | 296 | 4 | +6.96 | +26.92 | 8.1 | 293 | +2.15 | +15.70 |
| **v2 = all three** | **145** | 4 | **+0.13** | +20.08 | 9.8 | **147** | +5.17 | +18.72 |
| v2 without ask cap | 296 | 4 | +6.96 | +26.92 | 8.1 | 293 | +2.15 | +15.70 |
| v2 without z-gate | 220 | 11 | −23.98 | −4.03 | 28.1 | 213 | +4.89 | +18.44 |
| v2 without standard-only | 164 | 5 | +8.98 | +28.93 | 7.8 | 170 | −13.30 | +0.25 |

Reading **[F for the numbers, I for the causes]**:
* **Why only 145 trades:** standard-only barely cuts trade count (−4) because most of its effect is *re-timing* entries; z ≥ 1.5 removes ~42 more markets (test); **the ask cap is the filter that removes the most trades (−151 more on top of the other two)**, because after the other two filters most remaining entries are at ask > 0.97 (standard entries are by definition ≥ 0.95).
* **z ≥ 1.5 is the only filter with a consistent loss-avoiding effect on test** (18 → 5 losses alone; skipped 7 losing and 35 winning v1 trades), but on dev it alone was negative (−3.77): it does not help in both periods independently, only in combination with standard-only (+15.70 on dev).
* **The ask cap is not supported:** it lifted dev by ≈ +3.0 but cost ≈ −6.8 on test, while halving the sample. v2 without the cap has the higher test P&L (+6.96 vs +0.13) and the same drawdown. The dev-grid picked the cap by a small dev margin; treat it as noise. A cap-free variant is a better v2 candidate to test on new data (this is a post-hoc observation: it was not pre-registered).
* Standard-only is mixed: large dev gain (+17.9), small test gain (+5.8); the live early branch was flat (−$0.06) while live standard was −$5.98, so do not conclude the early branch should be dropped on this evidence.

**What cannot be validated with this data [M]:** book depth and queueing; true latency and the live ask at submission (decision logs); BRTI between the 15 s snapshots; whether live fills would behave like top-of-book; BRTI before Oct 21 (only 9–10 days, one regime); cross-regime generalisation (Oct 28–30 included the sharpest reversals). The replay reproduces 99% of live sides but only 79% of entry modes, and live fills beat my replay's prices on common trades (live per-5 +$1.33 vs replay −$1.11), so absolute dollar figures are indicative only.

## 9. Concrete v2 implementation plan (not implemented)

1. **Log first.** Before any rule change, persist per-decision: signal ask, book levels (top 3), preview limit, BRTI value/age, σ15, z, Φ(z), slopes, evaluation→submit latency, and the post-fill book. Closes the §2/§5 evidence gaps (#185/#210).
2. **Add `five_minute_momentum_v2` as a new strategy id** (do not edit v1). Reuse `evaluate_five_minute_direction` for direction. Add a pure function `momentum_v2_gate(history_brti, strike, seconds_left, ask, cfg)` beside `evaluate_momentum_entry` (`paper_strategy.py:1004`) returning BUY/SKIP with a reason; keep it I/O-free and unit-tested like `test_paper_momentum.py`.
   * σ15 from the last 20 BRTI observations of the current market (needs the collector's BRTI series or the runner's own samples; require ≥ 8 points, else skip).
   * Parameters (config, not constants): `z_min = 1.5` (also test 2.0), `standard_only = true`, `max_entry_ask = 0.98`, `min_edge = Φ(z) − ask − fee ≥ 0.0` (shadow), `min_strike_cushion_usd = 10`.
3. **Submit-time guard** in `_execute` (`auto_trading.py:~552-660`): abort if the re-read best ask differs from the signal ask by > 0.03 or the BRTI side flipped.
4. **Risk:** remove momentum v2 from `CONFIGURED_RISK_EXEMPT_STRATEGIES` (`live_strategies.py:15`) so daily loss/trade limits apply; fix size at ≤ 5 contracts.
5. **Shadow/paper phase (no real orders):** run v1 and v2 decisions side by side on the same live snapshots. Success criteria fixed in advance: ≥ 300 v2 shadow entries and ≥ 3 weeks / ≥ 2 distinct volatility regimes; net P&L > 0 at slip +$0.01 with the lower 80% interval above −$5; max drawdown below v1's; no unexplained fill-price deviations > 0.05. Do not retune thresholds on the shadow data without a new untouched period.
6. **Go-live:** minimum size, daily loss cap ≤ 3 average losses, kill-switch if 3 consecutive losses.

## 10. Honest limitations

* 8 live losses are too few to confirm any cause; the z-pattern was found after seeing them.
* The v1-vs-v2 comparison uses one 10-day, one-regime sample; the test period overlaps the live window and the same unusual days (Oct 28–30).
* Snapshot-based reconstruction cannot show what the 15 s runner saw 0–15 s later.
* Paper/replay results never prove profitability; the current evidence supports reducing exposure (z-gate, smaller size, loss limits) and collecting better logs, not scaling up.
