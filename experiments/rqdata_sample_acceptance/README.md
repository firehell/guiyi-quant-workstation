# RQData Small Sample Acceptance

This experiment validates the smallest real RQData data path:

```text
RQData credentials from environment variables
-> raw parquet
-> standard parquet
-> market_data_files / data_quality_reports
-> DuckDB
-> MarketDataReader / RQDataProvider
-> optional vn.py smoke backtest
```

It is a research acceptance demo only. It is not a formal backtest conclusion, does not use any trading account, does not call CTP, does not call TqSdk trading APIs, and does not place orders.

## Credentials

The script does not accept account names, passwords, tokens, or licenses as command-line arguments.

Set one of these environment configurations before running the real sample:

```bash
export RQDATAC2_CONF="..."
# or
export RQDATAC_CONF="..."
# or
export RQDATA_LICENSE_KEY="..."
# or
export RQDATA_USERNAME="..."
export RQDATA_PASSWORD="..."
```

The script never prints credential values.

## Commands

Check whether the environment is configured:

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py --check-credentials
```

Run the default small sample into an isolated SQLite database:

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py
```

Run the sample against the local development PostgreSQL app database:

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py \
  --contract RB2405 \
  --exchange SHFE \
  --symbol rb \
  --frequency 1m \
  --start 2024-01-02 \
  --end 2024-01-31 \
  --use-app-db
```

Optionally request a vn.py smoke backtest. The backtest only runs when the generated standard bars have `quality_status=passed`.

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py \
  --contract RB2405 \
  --exchange SHFE \
  --symbol rb \
  --frequency 1m \
  --start 2024-01-02 \
  --end 2024-01-31 \
  --use-app-db \
  --run-backtest
```

Run the P0-002 JM one-year raw download. This first resolves the RQData dominant contract mapping for `JM`, then downloads the actual dominant contract 1m raw bars for the latest complete calendar year. Use `--year` to pin a complete calendar year explicitly:

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py \
  --jm-one-year-raw \
  --product JM \
  --exchange DCE \
  --frequency 1m
```

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py \
  --jm-one-year-raw \
  --product JM \
  --exchange DCE \
  --frequency 1m \
  --year 2025
```

The script does not accept RQData account names, passwords, tokens, or license values as command-line arguments. Credentials are read from environment variables only.

Convert the P0-002 JM raw parquet into standard parquet, write `market_data_files` / `data_quality_reports`, and verify DuckDB, `MarketDataReader`, and `LocalParquetProvider` access:

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py \
  --standardize-jm-raw \
  --product JM \
  --exchange DCE \
  --frequency 1m
```

By default this reads `raw.path` from `experiments/rqdata_sample_acceptance/output/rqdata_jm_raw_result.json` and writes metadata to the isolated SQLite database under the ignored output directory. To pin a raw file explicitly, add `--raw-path /path/to/raw.parquet`.

## Output

All generated files are under:

```text
experiments/rqdata_sample_acceptance/output/
```

Expected files include:

```text
raw/rqdata/...
parquet/canonical/bars/provider=rqdata/...
rqdata_sample_result.json
rqdata_jm_raw_result.json
rqdata_jm_standard_result.json
rqdata_sample.sqlite
```

The output directory is ignored by Git. Do not force-add real RQData parquet files.

## Cleanup

```bash
rm -rf experiments/rqdata_sample_acceptance/output/*
touch experiments/rqdata_sample_acceptance/output/.gitignore
```
