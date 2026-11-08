# Repository Audit — pre-cleanup snapshot

Audit date: 2026-11-06. This document records the repository state before the public-portfolio cleanup. Findings about
files that were subsequently removed or replaced are retained as historical evidence, not as a description of the
current working tree. Figures were computed directly from the files (aggregates only; no secret values are printed).

## 1. Repository overview

- **Remote:** `origin` = `Ghostlun/analysis-report-AI`. **Current visibility: PRIVATE** (via `gh repo view`). The audit treats it as if it will become public.
- **History:** 7 commits (2026-10-29 → 2026-11-05), 46 tracked files.
- **Purpose (per README):** offline, read-only analysis of Kalshi `KXBTC15M` (15-minute BTC up/down binary markets). It is *not* a general BTC OHLC research repo.
- **Python:** 3.14.2 locally. No `requirements.txt`/`pyproject.toml`; README says `pip install pandas numpy scipy matplotlib`. Code also imports **scikit-learn** (`pattern_model.py`), which the README omits. Installed: pandas 3.1.0, numpy 2.5.4, scipy 1.18.1, scikit-learn 1.9.1, matplotlib 3.11.2. Versions are unpinned.
- **GitHub Actions:** none (`.github/` does not exist).
- **Docs:** `README.md` (good command reference) and 6 reports in `reports/`.

| Path | Contents |
|---|---|
| `run.py` | CLI entry (`actual`, `simulated`, `filters`, `check`, `model`, `gap`, `legacy`) |
| `src/` | `paths.py`, `momentum.py`, `pattern_model.py`, `gap_rule.py`, `kalshi_lib.py`, `kalshi_strats.py` |
| `scripts/` | `update_data.py` (refresh CSVs from Downloads/URL), `fetch_live_orders.py` (pulls from a local trading-bot export endpoint) |
| `experiments/` | 12 one-off scripts |
| `data/raw/` | `KXBTC15M_all.csv`, `live_orders_all.csv` (+ identical `.bak` copies, all tracked) |
| `outputs/actual`, `outputs/simulated` | 1 + 9 derived CSV/JSON files |
| `reports/` | 6 Markdown reports |
| `archive/` | original notebook + `.bak` (~225 KB each) |
| `AIRelated.ipynb` | short notebook (3 KB) calling `src` functions |

Not tracked (gitignored, present locally): `__pycache__/`, `.venv`, `.ipynb_checkpoints/`. No SQLite/DB files, no image artifacts, no dashboard JSON exist.

## 2. Dataset inventory

### 2.1 Primary datasets

**`data/raw/KXBTC15M_all.csv`** — CSV, 22.07 MB, **77,922 rows × 24 cols**, 0 duplicate rows, unique `id` (1..77922).
- Market identifier: `ticker` (1,334 markets, series `KXBTC15M` only). Timeframe: **single, 15-minute contracts**, sampled ~every 15 s (median gap 15.01 s, p95 15.10 s; ~59 rows/market median).
- Range: `collected_at_utc` 2026-10-16 13:29 → 2026-11-02 20:16 UTC (≈17 days). 11 collection gaps > 300 s (max ≈ 21 h).
- Timestamps: `collected_at_utc`, `source_timestamp`, `close_time` (no nulls), `reference_timestamp` (74% non-null), `settlement_timestamp` (2.4% null). All parse as UTC.

| Column(s) | Type | Nulls | Notes |
|---|---|---|---|
| `id` | int64 | 0 | |
| `ticker`, `status`, `reference_source`, `official_settlement_result`, `settlement_status` | str | 0 / 0 / 20,130 / 4 / 4 | `status`: active/closed/finalized/determined; `reference_source` only `cf_benchmarks_brti`; settlement result has 2 values |
| `collected_at_utc`, `source_timestamp`, `close_time`, `reference_timestamp`, `settlement_timestamp` | str (ISO UTC) | 0/0/0/20,130/1,888 | stored as strings; need parsing |
| `yes_bid_usd`, `yes_ask_usd`, `no_bid_usd`, `no_ask_usd` | float | 2,955 / 2,739 / 2,739 / 2,955 | 0.001–0.999; no crossed yes bid > ask |
| `last_price_usd` | float | 4 | |
| `volume_contracts` | float | 0 | contract volume (max 6.67 M) |
| `reference_price_usd` | float | 20,130 | BTC reference (BRTI) 76,178–82,916 |
| `btc_price_difference_usd`, `btc_price_difference_pct` | float | 20,137 | reference − strike |
| `seconds_until_close` | float | 20,084 | 0–893 |
| `floor_strike` | float | 0 | 76,370–82,912 |
| `cap_strike` | float | 77,922 (100%) | **entirely empty** |
| `official_final_btc_price_usd` | float | 4 | |

**`data/raw/live_orders_all.csv`** — CSV, 203.6 KB, **572 rows × 23 cols**, 0 duplicate rows. Range `intended_at` 2026-10-25 19:57 → 2026-11-02 19:40 UTC. Real account order history: 454 settled, 65 rejected, 52 canceled, 1 previewed; 3 strategies; 15 runs; all `market_ticker`s exist in the market file. Nulls: `exchange_order_id` 66, `average_fill_price_usd` 118, `settlement_result`/`realized_pnl_usd`/`balance_after_settlement_usd`/`settled_at` 118, `error_code` 473. Includes order/exchange IDs, fill cost, fees, realized P&L and **account balance after settlement** (see §5).

### 2.2 Derived outputs (all tracked)

| File | Rows × cols | Notes |
|---|---|---|
| `outputs/actual/momentum_trade_features.csv` | 373 × 27 | per live trade: ticker, fill, pnl, z, sigma15… — **derived from real trades** |
| `outputs/simulated/analog_model_train.csv` | 33,415 × 8 | features z, sec, d2..d20, label y |
| `outputs/simulated/momentum_v2_dev_grid.csv` | 192 × 9 | param grid: n, wins, net, maxdd |
| `outputs/simulated/pattern_model_by_time.csv` | 8 × 10 | Brier/accuracy of market vs logit/GBM/kNN by time bin |
| `outputs/simulated/pattern_model_policy_grid.csv` | 60 × 11 | dev/test EV per policy |
| `outputs/simulated/pattern_model_4min_gate.csv` | 30 × 10 | gate results (10 nulls in dev columns) |
| `outputs/simulated/gap_rule_results.csv` | 12 × 9 | 4 null rows |
| `outputs/simulated/{analog_model,gap_rule,pattern_logit_model}.json` | small | model parameters/thresholds |

### 2.3 Suitability

| Use | Verdict | Evidence |
|---|---|---|
| BTC price analysis | **Limited** | Only a BRTI spot value every ~15 s for ~12 days (reference non-null from 2026-10-21); no OHLC, no BTC volume, no multi-timeframe history. Reference series repeats across overlapping markets. |
| Technical indicators (RSI/EMA/SMA/MACD/ATR) | **No (as-is)** | No OHLC bars; could only be derived from a resampled ~12-day tick series; none implemented. |
| Prediction analysis | **Yes** | Settlement outcomes + market-implied prices + model outputs over ~1,328 settled markets. |
| Strategy research | **Yes** | Quote snapshots, fee logic, replay code, live results (572 orders). Short window (≈17 / 8 days). |

## 3. Existing analysis functionality

Documented from source signatures/docstrings. All are offline pandas/numpy code; there are no unit tests (only `python run.py check`, which asserts headline numbers from a report).

| Source | Function(s) | Inputs → Outputs | Dependencies | Limitations |
|---|---|---|---|---|
| `src/momentum.py` | `load_market`, `load_orders`, `fee`, `wilson` | CSV paths → DataFrames; fee(p,n); Wilson interval | pandas, scipy | Hard-wired to the two CSV schemas |
| `momentum.py` | `features(g,i)` | one market's snapshots → dict: `sigma15` (std of last ≤20 ref-price steps), `z` (\|diff\|/(σ√(sec/15))), `persist`, `toward` (60 s move), `ref_range_5m` | numpy | **The only volatility/momentum code**; 15 s-snapshot-specific |
| `momentum.py` | `v1_signal`, `candidates`, `replay`, `summarize`, `sim_candidates`, `dev_grid`, `chosen_v2`, `v1_vs_v2`, `paired_diff`, `filter_impact`, `trade_cumulative`, `fidelity` | snapshots → simulated trades, P&L, drawdown, bootstrap diffs, dev/test split (2026-10-27) | pandas, numpy | Encodes a private bot strategy; assumes N=5 contracts, +$0.01 slippage; replay matches only 79% of live entry modes (README) |
| `momentum.py` | `actual_audit`, `actual_trades`, `actual_losses`, `actual_buckets`, `actual_calibration` | live orders + market → reconciliation, per-trade features, calibration | pandas | **Operate on real account trades** (sensitive); buckets are post-hoc/descriptive |
| `momentum.py` | `plot_actual_cumulative`, `plot_sim_cumulative`, `plot_filter_impact`, `plot_loss_z` | tables → matplotlib figures | matplotlib | Figures not saved to files |
| `src/pattern_model.py` | `build_samples`, `fit_models`, `predict`, `accuracy_by_time`, `entry_policy`, `policy_grid`, `export_logit`, `export_analog`, `score_analog`, `decision_snapshots`, `gate_trade`, `four_minute_gate`, `run` | snapshots → P(yes) from logit / HistGradientBoosting / kNN; Brier + accuracy vs market; EV grids; JSON model exports | scikit-learn, numpy | Prediction accuracy only for 3 models vs market mid; small sample |
| `src/gap_rule.py` | `load_samples`, `fit_thresholds`, `replay`, `run` | % gap to strike → safe-entry thresholds per time bin (Wilson LB) | pandas, numpy | Thresholds fit on small dev set |
| `src/kalshi_lib.py` | `fee`, `size_buy`, `sell_fee`, `load_markets`, `add_features`, `Market`, `Trade`, `buy_fill`, `sell_fill`, `settle`, `run_strategy`, `summarize` (bootstrap CI) | markets → trades and summary stats | pandas, numpy, scipy | Kalshi-specific fee/sizing model |
| `src/kalshi_strats.py` | `baseline_95force`, `baseline_price_threshold`, `baseline_momentum`, `baseline_direction`, `rule`, `price_only_rule`, `exit_rule` | factories returning entry/exit callables | — | Mirrors private bot strategies |
| `scripts/update_data.py`, `fetch_live_orders.py` | `validate`, `fetch`, `atomic_replace`, `build_export_url`, … | export file/URL → refreshed CSVs | stdlib, pandas | `fetch_live_orders.py` targets `/api/auto-trading/orders/export` on a local bot (private API; couples repo to the private system) |
| `experiments/*.py` | 12 one-offs (`model_edge`, `strike_check`, …) | | pandas, numpy | Ad hoc; run via `run.py legacy` |

**Not present:** RSI, EMA, SMA, MACD, ATR, generic OHLC/volume analysis, Sharpe/Sortino, a generic backtesting engine, and any dashboard/JSON export layer. Rolling std (`sigma15`), 5-minute range, and a "toward" move are the only volatility/momentum measures. The README says nothing here calls a trading API; that holds for `src/`, but `scripts/fetch_live_orders.py` does call a bot HTTP endpoint.

## 4. Data quality findings

1. **Reference price is missing for 2026-10-16 → 10-20** (100% null) and ≈26% of rows overall; derived columns (`btc_price_difference_*`, `seconds_until_close`) have the same gaps. Usable BTC series ≈ 12 days.
2. `cap_strike` is 100% empty; `reference_source` has a single value.
3. Quote nulls: ~3.5–3.8% in each bid/ask column (one-sided books).
4. 11 collection gaps > 5 min (max ≈ 21 h); markets overlapping a gap are incomplete.
5. 4 rows lack settlement result/final price (latest, unsettled market); 1,884 rows `determined` vs 76,034 `finalized`.
6. Timestamps are ISO strings with varying fractional seconds (`format="mixed"` needed).
7. No duplicates in any file; `.bak` files are byte-identical to current CSVs (redundant ~22 MB tracked).
8. Live orders: 118 rows with null P&L/settlement; 34 `order_not_found_at_exchange` and 30 `not_found_after_reconciliation` errors — reconcile before reporting P&L.
9. Small samples (572 orders, ~1,300 markets, ~17 days) → wide uncertainty; dashboards must display this.
10. `analog_model_train.csv` has no market identifier.
11. Hygiene: UTF-8 BOM in some `src/*.py`; scikit-learn missing from README setup.

## 5. Security findings

Scope: working tree, all 7 commits (pattern search of diffs and file names), `.gitignore`. No values printed.

| # | Severity | Finding | Paths | Remediation |
|---|---|---|---|---|
| S1 | **High (if public)** | Personal trading records: order/exchange order IDs, fills, P&L, fees, **account balance after settlement** | `data/raw/live_orders_all.csv`, `data/raw/live_orders_all.csv.bak` | Remove from the public repo and **purge from history** (added in commit `f90e584`; e.g. `git filter-repo`); publish only aggregated/anonymized data |
| S2 | High (if public) | Per-trade data derived from live orders | `outputs/actual/momentum_trade_features.csv` | Exclude or aggregate; drop tickers/timestamps |
| S3 | Medium | Reports/notebooks describe real live outcomes and bot parameters/requests | `reports/*.md` (esp. `BOT_REQUEST_ANALOG_4MIN.md`, `MOMENTUM_V2_ANALYSIS.md`), `archive/*.ipynb` (+`.bak`) | Manual review; notebook outputs may embed data/balances |
| S4 | Medium | Private API route, local host, and references to the private trading bot | `scripts/fetch_live_orders.py`, `README.md` | Move scripts to the private repo |
| S5 | Low | Auth via env var `KALSHI_EXPORT_TOKEN` (name only; no value in code) | `scripts/update_data.py`, `scripts/fetch_live_orders.py`, README | Acceptable; keep scripts out of the public repo |
| S6 | Low | Proprietary strategy/model parameters | `outputs/simulated/*.json`, `src/kalshi_strats.py`, `analog_model_train.csv` | Decide whether strategy IP is to be public |
| S7 | Info | `.gitignore` lacks `.env*`, `*.bak`, `*.db`, `*.sqlite`, `*.log`, `data/raw/` | `.gitignore` | Extend |

**Negative results:** no `.env`, key/PEM, SQLite/DB, or log files tracked or in history; no hard-coded keys, tokens, or private-key blocks found by pattern scan of the tree and history (matches were only the env-var name and "bearer" wording). `__pycache__`/`.venv` are untracked. `KXBTC15M_all.csv` is exchange market data and appears safe, subject to Kalshi / CF Benchmarks redistribution terms.

Limitations: pattern scan only (gitleaks/trufflehog not run); GitHub-side secret scanning not checked.

## 6. Dashboard feasibility matrix

| Dashboard section | Status | Evidence |
|---|---|---|
| Market Overview | **Partially Ready** | BRTI reference price (15 s, 2026-10-21 → 11-02), strike, contract volume, implied probabilities exist. Missing: BTC OHLC/volume, longer history, aggregates; 5 days without reference price. |
| Technical Indicators | **Missing Required Data** | No OHLC and no indicator code; only ~12 days of 15 s ticks. |
| Prediction Analysis | **Partially Ready** | Settled outcomes plus model vs market Brier/accuracy by time bin and gap/pattern models exist. Gaps: small sample, no calibration-curve output or per-prediction records, no market ids in training export. |
| Strategy Research | **Partially Ready** | Replay code, EV grids, dev/test split, and live results exist. Gaps: live data is private, short window, no generic backtest/equity-curve export, results depend on assumed slippage. |

No section is "Ready": there is no dashboard-ready export layer and public-safe data is not separated from private data.

## 7. Recommended next steps

1. **Decide the publication approach**: stay private, or create a clean public repo/branch. Do not publish as-is.
2. Remove `live_orders_all.csv*` and `outputs/actual/*` from the public scope and purge history. No credentials were found, but balances/order IDs would be exposed.
3. Move `scripts/fetch_live_orders.py` and bot-specific reports to the private repo; keep only a sanitized aggregate of live performance.
4. Extend `.gitignore` (`.env*`, `*.bak`, `*.db`, `*.sqlite`, `*.log`, private data dir) and run a secret scanner (gitleaks) before publication.
5. Add a pinned `requirements.txt` (pandas, numpy, scipy, scikit-learn, matplotlib); drop redundant `.bak` files.
6. Source real BTC OHLCV (1m/1h/1d) from a public API; implement RSI/EMA/SMA/MACD/ATR with tests.
7. Create a `public_data/` export layer emitting versioned dashboard JSON (schema + `generated_at`) with validation.
8. Add tests for loaders, fee model, Wilson/bootstrap helpers.
9. Confirm redistribution terms for Kalshi and BRTI data.

### Blockers before Task 2

- **B1 (must resolve):** The repo and its history contain private live-trading data; choose a clean-repo vs history-rewrite strategy.
- **B2:** No BTC OHLCV source for indicators and a credible Market Overview.
- **B3 (clarify):** Whether Kalshi `KXBTC15M` snapshot data and strategy parameters are intended to be public.
- Non-blocking: no CI, unpinned dependencies, no tests.
