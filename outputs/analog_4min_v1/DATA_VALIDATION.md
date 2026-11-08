# analog_4min_v1 data validation summary

## Source and scope

- Source file: `data/raw/KXBTC15M_all.csv`
- Recorded reference source: `cf_benchmarks_brti` (CF Benchmarks BRTI)
- Full local reference timestamp range: 2026-10-21T03:06:51Z through 2026-11-02T20:16:15Z
- Full local market close range: 2026-10-16T13:30:00Z through 2026-11-02T20:30:00Z
- BRTI observation range included in the raw output: 2026-10-22T03:30:45Z through 2026-11-02T20:15:00Z
- Source rows: 77,922
- Source markets: 1,334
- No interpolation or synthetic prices were used.
- Raw JSON contains positive, de-duplicated BRTI observations from 15 minutes before close through close, sorted by UTC timestamp.

## Market coverage

- Settled markets with valid ticker, strike, close time and result: 1,333
- Markets included in `raw_analog_markets.json`: 941
- Markets included in `analog_model_train.csv`: 913
- Training labels: YES=429, NO=484
- Markets with one or more missing points on the exact 15-second close-minus-15m to close grid: 941
- Total missing exact-grid points across included markets: 2,254
- Duplicate reference timestamps removed: 0
- Non-positive or missing BRTI prices removed: 0

## Exclusions from raw JSON

- missing_required_5m_to_4m_window: 392
- unsettled_or_missing_result: 1

## Additional exclusions from training CSV

- fewer_than_21_contiguous_15s_snapshots: 28

## Feature construction

- Evaluation observation: collector row closest to 240 seconds before close, restricted to 225–255 seconds.
- Snapshot series: 21 exact, contiguous 15-second BRTI timestamps ending at the evaluation row's reference timestamp.
- `pct = 100 * ln(reference_price / floor_strike)`.
- `sigma`: population standard deviation (`ddof=0`) of the 20 changes, floored at 0.0001.
- Features: `z, sec, d2, d4, d8, d12, d20`; label `y` is YES=1 and NO=0.
- Scaler: population mean and standard deviation (`ddof=0`) over the training feature rows.

## Integrity checks

- Training columns are exactly: `z,sec,d2,d4,d8,d12,d20,y`.
- All training features and scaler values are finite.
- All scaler scales are positive.
- Model `k`: 150.
- `raw_analog_markets.json` SHA-256: `9697fe169e750ed924b4f5630310a727a78b9245d4d6e46d5ba6cebc105a4b87`
- `analog_model_train.csv` SHA-256: `a49a29dab9e9f17356a7c1d4f5d4ec8cbb396f8d5e60efab0c3b1014ebc2d9cd`
- `analog_model.json` SHA-256: `e92c9bd2b41a51cfc076a1cfa0f93fa85100c1ebe080d8540a843ec04bf9491e`

## Limitation

The local source ends at 2026-11-02T20:15:00Z. It does not contain markets after that timestamp, so this build does not claim coverage through the current date.
