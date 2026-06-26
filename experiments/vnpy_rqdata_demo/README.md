# vn.py + RQData Backend E2E Demo

This directory is a safe backend demo for validating the V1 research path:

```text
sample config
-> sample data provider
-> BacktestService task
-> BacktestTaskRunner
-> fake vn.py adapter
-> result converter
-> standard JSON
```

It is not part of the formal backend service, task queue, API, database schema, or Web workflow.
It is a research validation demo, not a formal backtest conclusion.

## Purpose

- Check whether the local workstation can import the backend adapter modules and optionally vn.py.
- Run a sample-data path without requiring a real RQData account or real Parquet data.
- Verify the service/runner/adapter/result-converter shape can produce Guiyi standard JSON.
- Preserve the V1 boundary: research only, no live trading.

## Files

- `README.md`: experiment purpose, usage, limits, and next steps.
- `sample_config.json`: local-only sample config with placeholder Parquet paths and no credentials.
- `run_demo.py`: CLI entrypoint for environment checks and sample standard JSON output.
- `output/.gitignore`: keeps generated demo JSON out of Git.

## Usage

Show CLI help:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --help
```

Check the local environment. This does not require RQData credentials and does not use a trading account:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --check-env
```

Run the sample backend chain. This uses built-in sample bars and a fake vn.py adapter:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --sample
```

Validate the sample config only:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --dry-run
```

## Output

Generated files are written under:

```text
experiments/vnpy_rqdata_demo/output/
```

Expected files:

- `environment_check.json`: import availability and safety flags.
- `sample_standard_result.json`: sample task metadata, data-provider metadata, fake adapter metadata, and normalized standard JSON.

The `output/` directory is ignored by Git except for `output/.gitignore`.

## Limits

- The demo script does not install vn.py or modify dependency files at runtime.
- This experiment does not call RQData directly.
- Sample mode does not require real K-line data; it uses built-in sample bars.
- This experiment does not call TqSdk, live gateway integrations, or trading interfaces.
- This experiment does not read or write account login material, licenses, or external service keys.
- This experiment does not run Alembic migrations or write to PostgreSQL.
- This experiment does not modify `data/`.
- This experiment does not enter the formal V1 API, RQ worker, or Vue Web flow.
- V1 does not do automated live trading.

## Expected Data Contract

The later runnable demo should read local standard bars with fields compatible with the V1 data lake:

```text
source
data_role
symbol
contract
exchange
vt_symbol
datetime
trading_day
interval
open
high
low
close
volume
turnover
open_interest
data_version
```

Formal V1 backtests should default to:

```text
data_role = primary
quality_status != failed
source = rqdata / local_parquet
```

## Next Steps

1. Replace the fake adapter with real `VnpyBacktestRunner` execution when the vn.py runtime path is stable.
2. Replace built-in sample bars with a small standard Parquet fixture or a known local slice.
3. Persist reports and trades through the formal backend service path.
4. Add an API/worker smoke demo that does not require Web.
5. After external review, decide whether to proceed to the Web backtest task page.
