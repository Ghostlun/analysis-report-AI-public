# Dashboard JSON Generator

Generates four read-only research dashboard files in `public/dashboards/`. The repository is **private**; the
`public/` folder name does not authorise publication. Every file carries
`publication_status: public_portfolio_aggregate` and `is_live: false`.

```powershell
python scripts/generate_dashboards.py                 # writes public/dashboards/*.json
python scripts/generate_dashboards.py --out some\dir  # alternate output folder
python -m unittest discover -s tests                  # all tests
```

## Inputs (only these)

* `data/raw/KXBTC15M_all.csv` — read through `shared.data_loader` (allowlisted columns only).
* `outputs/simulated/` — `pattern_model_by_time.csv`, `pattern_model_policy_grid.csv`, `pattern_model_4min_gate.csv`,
  `gap_rule_results.csv`, `momentum_v2_dev_grid.csv`.

Never read: `data/raw/live_orders_all.csv`, `outputs/actual/`, exported all-market models, credentials.

## Outputs

| File | Content |
|---|---|
| `market_overview.json` | Reference-price summary/series (15m, 1h), counts, settlement outcomes, implied-probability aggregates; contract volume explicitly unavailable |
| `technical_indicators.json` | SMA20, EMA20, RSI14, ROC12, realized vol (24 bars; bar and annualized) for 1m/5m/15m/1h, coverage and masks; ATR/VWAP/volume unavailable |
| `prediction_analysis.json` | Market baseline vs logistic/GBM/kNN by time bin: accuracy, Brier, skill, snapshot counts; calibration and market counts unavailable; no superiority claim |
| `strategy_research.json` | Simulated-only per-family distributions (trades, win rate, EV, SE, net, drawdown) with fee/slippage assumptions; no best pick |

Series are columnar arrays (`time[i]` aligns with every other array). Timestamps are UTC `YYYY-MM-DDTHH:MM:SSZ`;
missing values are `null`. `meta.generated_at` changes per run; all other content is deterministic for unchanged inputs.

## Safety gates (`shared/dashboard_schemas.py`)

1. Explicit schemas: every object lists all keys, requires them, and forbids extras (the schema is the allowlist).
2. Safety scan for forbidden key names/strings (tickers, order/account/credential words, strategy parameters, paths).
3. Source-file allowlist in `meta.source_files` (name + SHA-256 only; no paths).
4. NaN/Infinity rejected (`allow_nan=False`).
5. All four documents are built and validated **before** any write; files are written via temp file + `os.replace`, so a
   failure leaves existing outputs untouched.

## Integration notes

Schema version `1.0.0` (`meta.schema_version`). Consumers should check `meta.data_status.is_live === false`, render
`unavailable` states instead of zeros, and show `publication_status` so the aggregate-only scope remains explicit.
