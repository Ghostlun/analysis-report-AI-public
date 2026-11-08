# Data policy

This directory is the local input boundary for the research pipeline. Raw files are not intended to be published
with the portfolio repository.

## Expected local inputs

### `raw/KXBTC15M_all.csv`

Market snapshots used by the replay and analog-model pipelines. Relevant fields include:

- `ticker`, `collected_at_utc`, `close_time`;
- `yes_bid_usd`, `yes_ask_usd`, `no_bid_usd`, `no_ask_usd`;
- `reference_timestamp`, `reference_price_usd`, `reference_source`;
- `seconds_until_close`, `floor_strike`;
- `official_settlement_result`.

### `raw/live_orders_all.csv`

Order audit input used for actual-fill analysis. This file can contain account-level execution details and should be
treated as private even when it contains no API credentials.

## Publication rules

- Do not publish API keys, PEM files, account identifiers, client order identifiers, or raw account balances.
- Do not redistribute market or reference-price data until its source terms permit it.
- Prefer aggregate tables in `reports/` over row-level exports.
- Keep a local checksum and collection-period record for every frozen study.
- Never replace missing observations with synthetic or interpolated values unless a report explicitly defines and
  tests that transformation.

The `.gitignore` rules prevent new raw CSV/JSON files from being added accidentally. Files already present in Git
history require a separate history-cleaning decision before public release.

## Public test fixture

Run `python scripts/update_data.py` to create two deterministic synthetic markets under `data/example/`. The script
does not fetch external data, inspect Downloads, load credentials, or write into `data/raw/`. Generated rows use the
explicit source label `synthetic_test_fixture` and are suitable only for schema and pipeline tests.
