# Validation Findings

Scope: why `python run.py check` fails, and reconciliation of the realized-volatility definition.
No existing source code, expected values or datasets were modified. Investigation used a temporary copy of the
repository files (since deleted) so tracked outputs were not overwritten.

## 1. Result

`python run.py check` on the current data fails **8** of 10 checks (the earlier report of six was a truncated view;
the first two failures were scrolled out).

| Check | Got | Expected (hard-coded in `run.py`) |
|---|---|---|
| live settled momentum trades | 373 | 146 |
| live net P&L | −29.58 | −6.0343 |
| live fees | 10.68 | 2.9403 |
| test v1 trades | 633 | 342 |
| test v1 net | −41.66 | −19.95 |
| test v2 trades | 292 | 145 |
| test v2 net | −14.30 | +0.13 |
| test v2 max drawdown | 21.37 | 9.8 |

Passing: P&L identity (error ≈ 1e-15) and the selected v2 rule being unchanged.

## 2. Cause — **verified: dataset growth against stale hard-coded expectations**

* The expected values come from `reports/MOMENTUM_V2_ANALYSIS.md`, written when the live-order file had 307 rows
  (146 settled, through 2026-10-30 16:30 UTC) and the market file had about 60,195 rows / 1,032 tickers
  (through 2026-10-30 16:52 UTC).
* Commit `1528d4d` (2 Nov) replaced the orders file and added about 17.8k market rows. The test window
  (markets first seen on/after the 2026-10-27 split) therefore grew from Oct 27–30 to Oct 27–Nov 2.
* **Reproduction:** truncating the market data to `collected_at_utc ≤ 2026-10-30 16:52:59Z` (60,194 rows) and the orders
  to the first 307 ids made **all 10 checks pass**. The check logic and the calculations are therefore internally
  consistent.

| Candidate cause | Verdict |
|---|---|
| Dataset growth | **Confirmed** (reproduction above) |
| Stale hard-coded report expectations | **Confirmed** (same reproduction; expectations are literals in `run.py`) |
| Change in input selection | Not supported: same files, same split date, same selected rule |
| Existing calculation inconsistency | Not supported: identity check passes; old numbers reproduce exactly on old data |
| Other | Nothing found |

## 3. Related observations

* The committed `outputs/simulated/*.csv` files are current with the full data: rebuilding the test-period samples
  gives per-bin snapshot counts [666, 979, 1156, 2547, 2595, 2596, 5192, 6371] (identical to `pattern_model_by_time.csv`),
  with 649 test and 333 development markets. The dashboards therefore use current model/strategy results.
* On the larger sample the v2 momentum test net moved from +0.13 to −14.30, i.e. the apparent edge in the original
  report did not persist. Treat historical report conclusions as superseded.
* Refreshing the expectations in `run.py` is left to the repository owner; they were deliberately not edited to make the
  check pass.

## 4. Realized volatility reconciliation

`DASHBOARD_DATA_MAPPING.md` §2.3 originally gave `sqrt(Σ r²)`. The shared implementation
(`shared/indicators.py::realized_volatility`) is the **RMS of log returns**:

* `r_i = ln(C_i / C_{i−1})` on the resampled reference-price closes.
* `σ_bar = 100 · sqrt(mean(r_i²))` over the last *W* returns (W+1 closes needed).
* Zero-mean assumption (returns are not demeaned), so it is not the sample standard deviation.
* Units: **percent per bar**. Annualized variant: `σ_bar · sqrt(525600 / bar_minutes)`, **percent per year**,
  assuming 24/7 trading and independent returns. With ~12 days of data annualized figures are noisy.
* A flat series gives 0.0; insufficient history, gaps, partial bars or missing bars give `null`.

The mapping document has been updated to this definition, and the technical-indicator JSON carries the same text under
`parameters.volatility`.

## 5. Unresolved

* The market file at report time had 60,195 rows versus 60,194 with my cutoff (one row; immaterial, all checks pass) —
  the exact original cutoff is unconfirmed.
* The original order file is not retained in the working tree, so the reproduction used the first 307 ids of the current
  file; that the first 307 rows equal the old file is inferred, not verified.
