# Dashboard Data Mapping — Public Bitcoin Quantitative Research Dashboards

Status: design only. Builds on `docs/REPOSITORY_AUDIT.md`. **This repository stays private** until a separate security review and publication process is complete. Nothing here authorizes publishing any file. No code, data, visibility, history, or workflow was changed.

## 0. Global conventions

- **Entities that must never be conflated** (use these exact labels in JSON and UI):
  - `btc_reference_price_usd` — CF Benchmarks BRTI index level in USD per 1 BTC (source `reference_price_usd`). It is an *index*, not an exchange trade price.
  - `contract_price_usd` — Kalshi binary contract quote in USD per contract, bounded 0–1 (`yes_*`, `no_*`, `last_price_usd`). Interpreted as an implied probability only after the caveats in §1.1.
  - `contract_volume` — number of Kalshi contracts traded (`volume_contracts`). It is **not** BTC spot volume and has no BTC or USD-notional unit. BTC spot volume is not in the repo.
- Timestamps: ISO-8601 UTC strings ending in `Z`. Sampling: ~15 s snapshots (median 15.01 s).
- Time windows used by all dashboards: `data_start`/`data_end` are derived from data, never hard-coded.
- Every JSON file carries a `meta` block (§6.0) including `schema_version`, `generated_at`, `source_window`, `sample_counts`, and `disclaimers`.
- Evidence basis: aggregates in the audit (77,922 snapshots, 1,334 tickers, 2026-10-16 → 2026-11-02; reference price non-null only from 2026-10-21 03:06 UTC; 11 collection gaps > 300 s).

## 1. Dashboard 1 — Market Overview

### 1.1 Metric definitions, sources, formulas

Source file for all rows: `data/raw/KXBTC15M_all.csv` (call it **M**).

| Metric | Source columns | Formula / unit | Notes |
|---|---|---|---|
| BTC reference price | `reference_price_usd`, `reference_timestamp` | as-is; USD per BTC | Null for 20,130 rows (all of 10-16…10-20); `reference_source` = `cf_benchmarks_brti` only |
| Price difference from strike | `reference_price_usd`, `floor_strike` (or `btc_price_difference_usd`, `btc_price_difference_pct`) | `diff_usd = ref − floor_strike` (USD); `diff_pct = 100·ln(ref/floor_strike)` (percent, as the repo's `pattern_model` does). Source `btc_price_difference_pct` is reported in percent; confirm its definition (simple vs log) before use, differences are negligible at this scale | `cap_strike` is 100% null, so markets are one-sided "above floor strike" |
| Market-implied probability (YES) | `yes_bid_usd`, `yes_ask_usd` | `p_yes_mid = (yes_bid + yes_ask)/2`; fall back to `NULL` if either side is null. Unitless 0–1 | Checked: `yes_bid + no_ask = 1` exactly in all non-null rows. Mid is a quote-implied probability, not a calibrated one: it includes spread, fees, and last-seconds convergence to 0/1 |
| Spread | `yes_bid_usd`, `yes_ask_usd` | `yes_ask − yes_bid` (USD) | One-sided books ≈ 3.5–3.8% of rows |
| Last traded contract price | `last_price_usd` | as-is, USD per contract | |
| Contract trading volume | `volume_contracts` | per ticker: `max(volume_contracts)` = total contracts traded for that market; per snapshot change `Δ = vol_t − vol_{t−1}` (clip ≥0; non-decreasing in 99.999% of consecutive rows). Unit: contracts | Treat as **cumulative per market**. Median final per-market volume ≈ 3.06 M, which is large; verify Kalshi unit semantics (contracts vs fp-scaled) before publishing a figure |
| Time until close | `seconds_until_close` or `close_time − collected_at_utc` | seconds | `seconds_until_close` null in 20,084 rows; recompute from `close_time` (never null) rather than trusting the column |
| Market outcome | `official_settlement_result`, `official_final_btc_price_usd`, `settlement_status` | categorical yes/no; USD | 1,333 tickers settled (631 yes / 702 no per first-row value); latest ticker unsettled |

### 1.2 Aggregations for the dashboard

- `latest_snapshot`: most recent row per active ticker.
- `daily_summary` (UTC date): snapshot count, markets seen, yes-rate of settled markets, mean/median final contract volume, min/max/mean BTC reference (only for days with reference data).
- `reference_series`: BTC reference price downsampled to 1-minute last-observation (see §2.2). Must not be mixed with contract prices on the same axis without a dual-axis label.

### 1.3 Limitations
- No BTC OHLC, no BTC spot volume, no market cap/funding data.
- Only 12 days of BTC reference; 5 days blank.
- "Probability" labels must read "market-implied", never "forecast".
- BRTI is licensed data (see §8 Licensing).

## 2. Dashboard 2 — Technical Indicators

### 2.1 Verdict per indicator

Input series: **R** = `reference_price_usd` + `reference_timestamp` (or `collected_at_utc`) from M. R is a single price per observation (a 15 s *tick*), not bars.

| Indicator | Supported? | Requirement |
|---|---|---|
| SMA | Yes | after resampling |
| EMA | Yes | after resampling; first `N` bars are warm-up (null) |
| RSI (Wilder, 14) | Yes | close-only; after resampling |
| Price momentum | Yes | ROC on closes |
| Realized volatility | Yes | from log returns of resampled closes |
| ATR | **No — not computed** | needs true High/Low/Close bars. Pseudo-OHLC from a ~15 s index series would understate true range; BRTI is not an OHLC feed. Mark `status: "unavailable"` |
| MACD | Yes (derived from EMA); not requested, optional | |

### 2.2 Resampling requirements (required before any indicator)

1. **De-duplicate the index series.** The same BRTI value appears in rows of simultaneously collected overlapping markets; build R by keeping one row per distinct `reference_timestamp` (≈57.8 k unique values over ~12 days), sorted ascending.
2. Use `reference_timestamp` as the observation time, not `collected_at_utc` (collection lag). Fall back on `collected_at_utc` only if null; document which.
3. Restrict to the window from the first non-null reference (2026-10-21 03:06 UTC).
4. Resample to fixed bars, label right-closed, `close = last` observation in bar: **1m, 5m, 15m, 1h** (1h gives ≈ 290 bars, enough only for SMA/EMA up to ~50 and RSI 14; no daily indicators — ≈ 12 daily bars).
5. **Gap handling:** do not forward-fill across the 11 collection gaps. Bars with no observation are null; indicators restart (or are masked) across gaps longer than 2 bars. Report `gap_count` and masked-bar count.
6. Floating UTC alignment; leave the final incomplete bar flagged `partial: true`.

### 2.3 Formulas (on closes `C_t` of bars; `N` in bars)

| Indicator | Formula | Unit |
|---|---|---|
| SMA_N | `mean(C_{t−N+1..t})` | USD |
| EMA_N | `EMA_t = α·C_t + (1−α)·EMA_{t−1}`, `α = 2/(N+1)`, seeded with SMA_N | USD |
| RSI_14 | Wilder: `avgGain/avgLoss` smoothed with `(prev·13 + x)/14`; `RSI = 100 − 100/(1+RS)` | 0–100 |
| Momentum (ROC_N) | `100·(C_t / C_{t−N} − 1)` | percent |
| Realized vol (window W bars) | **Reconciled in Task 4 to the shared implementation:** RMS of log returns, `σ_bar = 100 · sqrt( (1/W) · Σ r_i² )` over the last W returns, `r_i = ln(C_i/C_{i−1})` (needs W+1 closes; zero-mean assumption, returns are **not** demeaned, so it is not a sample standard deviation). The earlier draft `sqrt(Σ r_i²)` (no `1/W`) was a sum-of-squares estimator and is superseded. Annualized (optional): `σ_ann = σ_bar · sqrt(525,600 / bar_minutes)`, assuming 24/7 trading and independent returns; very noisy on a ~12-day sample. See `docs/VALIDATION_FINDINGS.md` §4 | **percent** per bar (`*_bar_pct`) or percent per year (`*_ann_pct`) |
| ATR | **not calculated** | — |

Existing repo code that overlaps: only `momentum.features()` (`sigma15`, 5-minute range) and `pattern_model` pct-gap features. They are 15 s-tick contract features, **not** reusable as the above indicators; the indicator functions are new work (documented, not implemented here).

### 2.4 Limitations
- Index levels, not OHLCV; no volume-weighted indicators (VWAP/OBV) are possible.
- Short history makes long-period EMAs (e.g. 200) invalid; the spec limits periods so that `N ≤ bars/3`.
- Indicators here describe a 12-day sample and must be labeled "sample period".
- Recommended supplement (not yet available): licensed/public BTC OHLCV 1m–1d.

## 3. Dashboard 3 — Prediction Analysis

### 3.1 Available inputs

| Item | Source | Exact columns | Notes |
|---|---|---|---|
| Settlement outcomes | M | `ticker`, `official_settlement_result` (yes/no), `settlement_status`, `settlement_timestamp` | Label `y = 1` if "yes" (as `pattern_model.build_samples`) |
| Market baseline probability | M | `yes_bid_usd`, `yes_ask_usd` → mid | Baseline "model" |
| Accuracy / Brier by time left | `outputs/simulated/pattern_model_by_time.csv` | `sec_bin`, `n`, `brier_market`, `acc_market`, `brier_logit`, `acc_logit`, `brier_gbm`, `acc_gbm`, `brier_analog_knn`, `acc_analog_knn` | 8 bins from (30,60] to (420,600]; test period only; n = 666…6,371 **snapshots** (sum ≈ 22.1 k) |
| Model comparison | same file + `pattern_model_4min_gate.csv` (aggregate gate) | | `pattern_model_policy_grid.csv` is strategy-oriented → Dashboard 4 |
| Model definitions (names only) | `src/pattern_model.py` | logit, HistGradientBoosting, kNN analog | Coefficients/hyperparameters are **excluded** (§5) |
| Training sample size | `outputs/simulated/analog_model_train.csv` | row count only (33,415) | The file itself is excluded (§5) |

Formulas: `Brier = mean((p − y)²)` (lower is better; 0.25 = always-0.5); `accuracy = mean(1[(p ≥ 0.5) == y])`. Derived "Brier skill vs market" = `1 − Brier_model/Brier_market` (unitless; negative = worse than market). Counts reported: `n_snapshots`, and `n_markets` (**not currently in the CSV**; see gaps).

Observed in existing file (for sanity checks only): models are within ±0.008 Brier of the market baseline in every bin; none is consistently better. The dashboard must show that plainly.

### 3.2 Leakage risks
1. **Snapshot-level evaluation.** ~59 correlated snapshots per market; `n` counts snapshots, not independent markets. Standard errors are overstated in confidence.
2. **Train/test split is by first-seen date (2026-10-27) over ~1,300 markets; test is the last ~6 days only.** No walk-forward or rolling evaluation; one regime.
3. **`export_analog` fits on ALL markets** (including test) and `analog_model_train.csv` contains all-market rows. Any metric computed from that exported model is in-sample. Evaluation metrics must come only from the dev-fit/test-judged path in `run()`.
4. **Hyperparameters / policies selected on the dev set** but thresholds like `conf` in the 4-minute gate and `margin`/`window` grids were examined on test too (grids print test results), creating selection bias; top-row test EVs are optimistic (multiple comparisons: 60 + 30 cells).
5. Features at snapshot i use data ≤ i (documented), but `sigma` uses the trailing 20 steps including `diff` of the reference series that is null before 10-21 — markets starting during null windows are dropped (survivorship by data availability).
6. The market mid used as baseline includes information from other participants after the same snapshot; "beating" it is not a fair claim unless fills are feasible.
7. `official_*` fields are post-settlement; they must never feed features (they do not in the current code).

### 3.3 Calibration limitations
- No reliability-curve (binned predicted vs observed) output exists; the dashboard cannot show calibration until it is generated.
- Probabilities concentrate near 0/1 close to expiry; sparse middle bins.
- Test-set sample (~800 markets) → wide intervals; require Wilson/bootstrap intervals by market, not snapshot.

### 3.4 Missing prediction records
No file stores per-prediction records (`ticker`, `snapshot time`, `p_model`, `y`). `pattern_model.run()` computes `p_logit`, `p_gbm`, `p_analog_knn` in memory only. Needed for calibration, per-market sample counts, and reproducibility. Such a file would be an internal intermediate; the public JSON would contain only binned aggregates (not tickers or timestamps).

## 4. Dashboard 4 — Strategy Research

### 4.1 Available aggregate sources (all SIMULATED unless stated)

| Item | Source | Exact columns |
|---|---|---|
| Dev-grid results | `outputs/simulated/momentum_v2_dev_grid.csv` | `mode, zmin, persist, maxp, n, wins, net, net_lo, maxdd` — **parameter columns excluded**; use only aggregate columns of selected-by-rank rows if at all |
| Policy EV | `pattern_model_policy_grid.csv` | `model, margin, window, n_dev, ev_dev, n_test, wr_test, ev_test, ev_test_se, n_test_delay, ev_test_delay15s` — `margin`/`window` excluded; keep `model`, counts, `wr_test`, EV |
| 4-minute gate | `pattern_model_4min_gate.csv` | `model, conf, fill, n_dev, ev_dev, n_test, wr_test, avg_price_test, ev_test, ev_test_se` — `conf` excluded |
| Gap rule | `gap_rule_results.csv` | `target_wilson_lb, fill, period, n, wr, avg_price, ev_per_contract, se, avg_sec` — `target_wilson_lb` is a tunable parameter → excluded or generalized |
| v1 vs v2 / paired diff / drawdown | functions `momentum.v1_vs_v2`, `paired_diff`, `summarize`, `trade_cumulative` (computed on demand; not stored) | n, win rate, net P&L, max drawdown, bootstrap CI |
| Actual live results | `data/raw/live_orders_all.csv`, `outputs/actual/*` | **Not used** by this dashboard (§5) |

### 4.2 Metric definitions
- **Win rate** = `wins / n`, with Wilson 95% interval (`momentum.wilson`).
- **EV per contract (USD)** = `mean(payout − price_paid − fee − slippage)` per contract; `ev_test_se` is the standard error. Unit: USD/contract (payout 1.00 for the winning side).
- **Net P&L (USD)** at N=5 contracts per trade (stated assumption).
- **Max drawdown (USD)** = max peak-to-trough drop of cumulative net P&L ordered by entry time; present as simulated-fixed-size USD, not account percent (no account equity is published).
- **Fees:** Kalshi fee model implemented in `src/momentum.py::fee` and `src/kalshi_lib.py::fee/size_buy/sell_fee`. The exact coefficients must be taken from the code at generation time and cited with the Kalshi fee-schedule date; do not hard-code in this document.
- **Slippage assumptions:** +$0.01 per contract (`slip+0.01`) and a 15-second delayed-fill scenario (`delay15s`, fill at next snapshot's ask). Published as scenario labels.

### 4.3 Limitations
- Simulated fills on 15 s snapshots; replay matches 99% of live sides but only 79% of live entry modes (README), so dollar results are indicative.
- ≈17 days, 2 periods (dev < 2026-10-27 ≤ test), multiple-testing across grids; many cells have EV ≈ 0 (e.g. gap rule at 0.90 target: test EV ≈ −0.0001, SE ≈ 0.013 — statistically zero).
- Delayed-fill scenario turns several positive EVs negative; the dashboard must display both scenarios side by side.
- No transaction history for live trades may appear; the public dashboard shows *research* strategies as generic families ("momentum", "pattern model gate", "gap rule") **without parameters or thresholds**.
- No benchmark comparison (buy-and-hold BTC) is possible: no BTC returns for the full window.
- Disclaimer required: educational research, not investment advice; past simulated performance does not predict results.

## 5. Public-data security policy

### 5.1 Strict allowlist (default deny)

A field may appear in public JSON **only** if it is listed here. Generators must validate output against this list and fail on unknown keys.

| Group | Allowed fields |
|---|---|
| Meta | `schema_version, generated_at, source_window.{start,end}, data_freshness.*, sample_counts.*, units.*, disclaimers[], status, notes` |
| Market (aggregated/downsampled) | `time` (bar close, UTC), `btc_reference_price_usd`, `btc_diff_from_strike_usd`, `btc_diff_from_strike_pct`, `implied_prob_yes_mid`, `spread_usd`, `contract_volume_total`, `seconds_to_close`, `markets_count`, `settled_yes_share`, `date`; plus `open/high/low/close` **only for index bars derived from reference price, labeled `index`, never named ATR inputs** |
| Indicators | `bar_minutes, time, close, sma_N, ema_N, rsi_N, roc_N_pct, realized_vol_W_pct, partial, indicator_status` (ATR = `unavailable`) |
| Prediction (aggregate) | `model_family` (`market_baseline`, `logistic`, `gradient_boosting`, `knn_analog`), `time_bin`, `n_snapshots`, `n_markets`, `brier`, `accuracy`, `brier_skill_vs_market`, calibration bins (`p_lo, p_hi, n, mean_pred, observed_rate, ci_lo, ci_hi`), `evaluation_period` |
| Strategy (aggregate) | `family`, `scenario` (`immediate`, `slip_0.01`, `delay_15s`), `period` (`dev`, `test`), `n_trades_simulated`, `win_rate`, `win_rate_ci_lo/hi`, `ev_per_contract_usd`, `ev_se_usd`, `net_pnl_usd_simulated`, `max_drawdown_usd_simulated`, `assumptions.{contracts_per_trade, slippage_usd, fee_model_ref, fill_delay_s}`, cumulative curve as `{trade_index, cum_pnl_usd}` (index not time, aggregated over ≥ 20 trades) |

Rules: round prices to the source tick; no per-order rows; counts below 10 suppressed (`null`); timestamps only for market series (bar-level), never tied to any order.

### 5.2 Excluded (denylist; non-exhaustive)

| Dataset / file | Reason | Excluded columns |
|---|---|---|
| `data/raw/live_orders_all.csv` (+`.bak`) | personal trading records | **all**: `id, run_id, strategy_id, market_ticker, side, entry_mode, intended_at, manual_intent_id, client_order_id, exchange_order_id, status, requested_contracts, filled_contracts, average_fill_price_usd, fill_cost_usd, fees_usd, maximum_cost_usd, settlement_result, realized_pnl_usd, balance_after_settlement_usd, settled_at, error_code, error_message` |
| `outputs/actual/momentum_trade_features.csv` | per-live-trade derived data | all (`ticker, t, fill, fees, pnl, qty, official_px…`) |
| `outputs/simulated/analog_model_train.csv`, `analog_model.json`, `pattern_logit_model.json`, `gap_rule.json` | proprietary model parameters/training rows | all |
| `momentum_v2_dev_grid.csv`, grid columns | tunable strategy parameters | `zmin, persist, maxp, mode, margin, window, conf, target_wilson_lb` |
| `data/raw/KXBTC15M_all.csv` raw rows | not published raw (see §8) | `id, ticker` (only aggregated/anonymous market ids if needed), `source_timestamp`, `status`, `cap_strike`, `reference_source` (use the constant attribution), raw bid/ask per ticker |
| `reports/*.md`, `archive/*`, `*.bak`, `scripts/fetch_live_orders.py` | narrative of live trading, private API | all |
| Any bot, account, endpoint, env var, balance, order or run identifier | privacy / security | all |

### 5.3 Licensing / redistribution questions (unresolved — must be answered before publication)
1. **CF Benchmarks BRTI:** may index levels (derived 15 s/1m values) be redistributed publicly? Delayed vs real-time rules, attribution, display restrictions. The 12-day series is a copy of a licensed index as ingested via Kalshi.
2. **Kalshi market data:** do Kalshi's API/data terms allow republishing quotes, volumes, and settlement results? Are derived aggregates distinct from raw quotes under their terms? How was the data collected (public API vs authenticated) and under which agreement?
3. Is displaying "implied probabilities" from a regulated exchange permitted with a disclaimer?
4. Attribution/trademark requirements for names "Kalshi", "BRTI".
5. Whether strategy-family results constitute investment-advice-like content in the owner's jurisdiction (disclaimer, no performance claims).
6. Public data is not automatically safe: derived series can reveal collection times/infrastructure behavior and, joined with the private order file, could re-identify trades (e.g., fills at exact timestamps). Publishing only coarse aggregates mitigates this.

## 6. Proposed JSON schemas (draft, JSON Schema style; `additionalProperties: false` everywhere)

### 6.0 Common `meta`
```json
{
  "meta": {
    "schema_version": "1.0.0",
    "dashboard": "market_overview | technical_indicators | prediction_analysis | strategy_research",
    "generated_at": "2026-11-06T00:00:00Z",
    "source_window": {"start": "2026-10-21T03:06:51Z", "end": "2026-11-02T20:16:15Z"},
    "sample_counts": {"snapshots": 0, "markets": 0},
    "units": {"btc_reference_price_usd": "USD per BTC (BRTI index)", "contract_price_usd": "USD per contract, 0-1", "contract_volume": "Kalshi contracts"},
    "data_attribution": "TBD pending licensing review",
    "disclaimers": ["Research only. Not investment advice.", "Sample period only; results may not persist."]
  }
}
```

### 6.1 `market_overview.json`
```json
{
  "meta": {},
  "latest": {"time": "", "btc_reference_price_usd": 0, "btc_diff_from_strike_usd": 0,
             "btc_diff_from_strike_pct": 0, "implied_prob_yes_mid": 0, "spread_usd": 0,
             "seconds_to_close": 0, "contract_volume_total": 0},
  "reference_series_1m": [{"time": "", "btc_reference_price_usd": 0}],
  "daily_summary": [{"date": "", "snapshots": 0, "markets": 0, "settled_yes_share": 0,
                      "median_contract_volume_total": 0, "ref_min_usd": 0, "ref_max_usd": 0}],
  "implied_prob_by_time_left": [{"time_bin": "(30,60]", "n_snapshots": 0, "mean_implied_prob_yes": 0, "observed_yes_rate": 0}],
  "coverage": {"reference_available_from": "", "gap_count": 0, "null_reference_share": 0}
}
```
Note: `time` is the snapshot or bar time; `contract_volume_total` per market; nothing named *volume* without the `contract_` prefix.

### 6.2 `technical_indicators.json`
```json
{
  "meta": {},
  "bar_minutes": [1, 5, 15, 60],
  "series": {"60": [{"time": "", "close": 0, "sma_20": null, "ema_20": null, "rsi_14": null,
                      "roc_12_pct": null, "realized_vol_24_pct": null, "partial": false}]},
  "indicator_status": {"sma": "available", "ema": "available", "rsi": "available",
                        "momentum": "available", "realized_volatility": "available", "atr": "unavailable_no_ohlc"},
  "parameters": {"sma": [20], "ema": [20], "rsi": 14, "roc": [12], "realized_vol_window": [24]},
  "data_quality": {"gap_count": 0, "masked_bars": 0, "resampling": "dedupe by reference_timestamp; last in bar; no forward fill"}
}
```
Indicator parameters shown are standard public ones; they are not strategy parameters.

### 6.3 `prediction_analysis.json`
```json
{
  "meta": {},
  "evaluation": {"train_period": "before 2026-10-27", "test_period": "2026-10-27 onward", "unit_of_analysis": "snapshot",
                  "n_test_snapshots": 0, "n_test_markets": 0, "caveats": ["snapshots are correlated", "single split", "no walk-forward"]},
  "by_time_bin": [{"time_bin": "(30,60]", "n_snapshots": 0, "n_markets": null,
                    "models": {"market_baseline": {"brier": 0, "accuracy": 0},
                               "logistic": {"brier": 0, "accuracy": 0, "brier_skill_vs_market": 0},
                               "gradient_boosting": {}, "knn_analog": {}}}],
  "calibration": {"status": "not_available", "bins": []},
  "outcome_base_rate": {"settled_markets": 0, "yes_share": 0, "yes_share_ci": [0, 0]}
}
```
`n_markets` and `calibration.bins` are `null`/`not_available` until the missing prediction records exist.

### 6.4 `strategy_research.json`
```json
{
  "meta": {},
  "assumptions": {"contracts_per_trade": 5, "slippage_usd": 0.01, "fill_delay_s": [0, 15],
                   "fees": "Kalshi fee schedule, as implemented in code, version TBD", "data": "simulated replay on 15 s snapshots"},
  "families": [{"family": "pattern_model_gate", "scenario": "slip_0.01", "period": "test", "n_trades_simulated": 0,
                 "win_rate": 0, "win_rate_ci": [0, 0], "ev_per_contract_usd": 0, "ev_se_usd": 0,
                 "net_pnl_usd_simulated": null, "max_drawdown_usd_simulated": null}],
  "equity_curves": [{"family": "", "scenario": "", "points": [{"trade_index": 0, "cum_pnl_usd": 0}]}],
  "limitations": ["simulated fills", "multiple comparisons", "short window", "delayed-fill scenario reduces EV"]
}
```
`families` limited to generic names; no thresholds. Live results are absent by design.

## 7. Dashboard implementation priority

| Rank | Dashboard | Rationale | Data needed beyond current files |
|---|---|---|---|
| 1 | **Market Overview** | Directly computable from M; lowest risk once licensing is cleared | None for a first version; licensing answers |
| 2 | **Prediction Analysis** | Aggregate CSV exists; adding calibration/market-level counts needs a re-run that stores per-prediction records | Per-prediction records (internal), market-level counts |
| 3 | **Technical Indicators** | Computable from de-duplicated reference series, but limited (12 days, no ATR) and low analytical value until a longer OHLCV source exists | Preferably licensed BTC OHLCV for ATR and long windows |
| 4 | **Strategy Research** | Highest sensitivity (strategy IP, live data entanglement), results mostly statistically indistinguishable from zero; needs parameter-stripped aggregation and the fee/slippage review | Strategy publication decision; stored equity curves; benchmark |

## 8. Data freshness and update requirements

| Dashboard | Source refresh | Cadence | Staleness limit | Notes |
|---|---|---|---|---|
| Market Overview | re-export `KXBTC15M_all.csv` (currently a manual download via `scripts/update_data.py`) | daily (24 h) minimum for a research site; real-time not supported | `data_end` older than 48 h → `status: stale` | Real-time display of BRTI/Kalshi may be restricted by license |
| Technical Indicators | same | daily | same; mask incomplete last bar | Recompute full series each run (deterministic) |
| Prediction Analysis | same + re-run `python run.py model` | weekly, or when ≥ 100 new settled markets | stamp `trained_through` and `test_period` | Must refit dev-only and evaluate on later markets; record split date |
| Strategy Research | same + re-run simulations | weekly | stamp assumptions | Manual review before every release (security gate) |

General requirements: generator must be deterministic and idempotent; write a `meta.generated_at` and source file hash; validate with schema + allowlist (§5) and fail closed; secret/PII scan (gitleaks) before any publish; no automated publishing until the separate security review completes; the existing collection has no scheduler, so freshness today depends on manual exports (the `.bak` mechanism keeps one prior copy only); gaps > 5 min must be reported in `coverage`.

## 9. Which dashboards can be generated from existing data

| Dashboard | Verdict | Dependency |
|---|---|---|
| Market Overview | **Can be generated** (12-day window) | licensing review; no BTC spot volume or OHLC |
| Technical Indicators | **Partially**: SMA, EMA, RSI, momentum, realized vol after resampling; **ATR not possible** | needs OHLCV source for ATR, longer history |
| Prediction Analysis | **Partially**: by-time-bin Brier/accuracy/model comparison available now; calibration, market-level counts, leakage-safe re-evaluation need new internal outputs | prediction records |
| Strategy Research | **Partially**: simulated aggregates exist; drawdown/equity not stored; needs parameter-stripped regeneration and strategy-IP decision | publication decision; no live data |

Open decisions for the owner: licensing answers (§5.3), whether strategy families may be published, and whether to add an external BTC OHLCV source.
