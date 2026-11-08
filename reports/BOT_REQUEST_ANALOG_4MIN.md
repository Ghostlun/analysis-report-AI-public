# Request to the trading bot: `analog_4min_v1`

Copy the section "Request" into the bot task. Spec and validation: `reports/ANALOG_4MIN_ENTRY.md`. Files to hand over: `outputs/simulated/analog_model.json`, `outputs/simulated/analog_model_train.csv`, and `pattern_model.score_analog` / the feature definitions in `src/pattern_model.py` (`build_samples`).

## Request
Add a new strategy `analog_4min_v1` to KXBTC15M. Do not change momentum_v1.

1. **Decision time.** Once per market, at the first snapshot with seconds-to-close <= 240 (accept the snapshot closest to 240 s; skip the market if no snapshot falls in 225-255 s).
2. **Features** (use the same reference price and strike as the market data; no data after the decision time):
   - `pct = 100*ln(reference_price/floor_strike)` for every 15 s snapshot of this market so far.
   - `sec` = seconds to close; `sigma` = std of `pct` change per snapshot over the last 20 snapshots (floor 1e-4);
     `z = pct/(sigma*sqrt(sec/15))`; `d_n = (pct_now - pct_{now-n snapshots})/(sigma*sqrt(n))` for n = 2, 4, 8, 12, 20.
   - If fewer than 21 snapshots exist, skip and log the reason.
3. **Score.** Load `analog_model.json` and `analog_model_train.csv` once at startup. Standardize `[z, sec, d2, d4, d8, d12, d20]` with the stored mean/scale, take the 150 nearest training rows (Euclidean), weight by 1/distance, `p_yes` = weighted share of `y=1` (rows at distance 0: use only those). Reference code: `score_analog`. It must reproduce `p_yes` from the Python reference to within 1e-6 on the provided test vectors (ask me for them or generate with `score_analog`).
4. **Entry.** `side = YES if p_yes >= 0.5 else NO` (`p_no = 1 - p_yes`), `prob = max(p_yes, p_no)`. Buy `side` at the ask (limit at ask + 0.01 at most) and hold to settlement. **No probability threshold and no skipping** (`min_prob` default 0.5; the value is a config so it can be raised later). The only technical skips: ask + 0.01 > 0.99, or missing/stale data. One entry per market.
5. **Config** (no redeploy to change): `enabled`, `shadow_mode` (log everything, place no order), `contracts` per trade, `min_prob` (default 0.5 = always enter), `max_price` (default 0.99), `max_trades_per_day`, `max_daily_loss_usd`.
6. **Safety.** Stop trading for the day when `max_daily_loss_usd` is reached; never double-enter a market; if the model files or reference price are missing/stale (> 20 s old), skip and log; kill switch via `enabled=false`.
7. **Logging.** Write every decision (including skips) and every fill/settlement as described below. Start with `shadow_mode=true` for a few hundred markets if possible, otherwise with a very small `contracts`.

## What to log
One record per market decision (`analog_4min_decisions`), written even when no trade is made:

| Field | Why |
|---|---|
| `market_ticker`, `decision_time_utc`, `close_time_utc`, `seconds_to_close` | identify and timestamp the decision |
| `reference_price_usd`, `floor_strike`, `pct` | gap used by the model |
| `n_snapshots_used`, `sigma`, `z`, `d2`, `d4`, `d8`, `d12`, `d20` | exact model inputs (lets us recompute the score offline) |
| `p_yes`, `p_no`, `side`, `prob`, `min_prob`, `model_version` (hash of the two model files) | model output and settings |
| `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `book_age_ms` at decision time | price we saw and how stale it was |
| `action` (`buy` / `skip`), `skip_reason` (`price_above_max`, `missing_data`, `daily_loss_cap`, `shadow_mode`, `already_entered`, `disabled`, `prob_below_min_prob` only if `min_prob` is raised) | why we did or did not trade |

One record per order (`analog_4min_orders`):

| Field | Why |
|---|---|
| `market_ticker`, `order_id`, `side`, `contracts`, `limit_price`, `order_sent_utc` | order details |
| `fill_time_utc`, `filled_contracts`, `avg_fill_price`, `fees_usd`, `status`, `error_code` | actual fills; `fill_time - decision_time` shows latency |
| `slippage = avg_fill_price - ask_at_decision` | check the +$0.01 assumption |

After settlement (join to the decision/order record): `settlement_result`, `win` (1/0), `realized_pnl_usd`.

Also log every 15 s of this market from the decision time to close (`pct`, bid/ask for both sides) if storage allows; it lets us test whether the quote or the reference price moves first and refine timing.

## What to check after the first 200-300 markets
- Share of markets that trade (expected ~80%; the rest have ask + 0.01 > 0.99 or missing data) and the overall win rate (expected ~77%, average price ~0.78, EV about -0.02 per contract with no threshold).
- Win rate by `prob` bucket (0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9+): expected about 51%, 63%, 81%, 92%, 97%+. If the low buckets keep losing, raise `min_prob` to 0.8 (config change).
- Average `slippage` (>= $0.02 removes any edge) and average `fill_time - decision_time`.
- Re-run `python run.py model` on the new data, and compare logged `p_yes`/`p_no` to outcomes.
