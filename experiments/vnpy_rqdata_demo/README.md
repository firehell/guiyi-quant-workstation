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
- `sample_config.json`: local-only sample config pointing at the standard Parquet fixture and no credentials.
- `generate_standard_fixture.py`: deterministic synthetic 60m bar fixture generator.
- `run_demo.py`: CLI entrypoint for environment checks and sample standard JSON output.
- `output/.gitignore`: keeps generated demo JSON out of Git.

The standard fixture path is:

```text
services/quant-api/tests/fixtures/standard_parquet/canonical/bars/provider=local_parquet/interval=60m/exchange=SHFE/symbol=rb/contract=rb2405/rb2405_60m.parquet
```

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

Run the standard Parquet fixture through the real vn.py CTA `BacktestingEngine`.
This injects fixture bars into `engine.history_data` and does not call vn.py data loading, RQData, a live gateway, or Studio:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --fixture-backtest
```

Run the backend end-to-end acceptance demo. This uses the fixture, creates a backtest task, executes the real vn.py runner, persists the report/trades/curves, queries the FastAPI report endpoints through `TestClient`, and writes a JSON summary:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --backend-e2e
```

By default this uses an isolated temporary SQLite database so it does not write to the configured PostgreSQL app database. For an explicit local development database smoke run, add `--use-app-db`.

Run the P0-005 real JM local-data smoke. This reads the P0-004 5m/15m standard Parquet paths from the ignored `rqdata_jm_aggregate_result.json`, injects bars into `VnpyBacktestRunner`, and writes a smoke summary without calling RQData, CTP, TqSdk, vn.py `load_data()`, or VeighNa Studio:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --jm-smoke-backtest
```

Generate or refresh the deterministic standard Parquet fixture:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/generate_standard_fixture.py
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
- `real_fixture_standard_result.json`: standard Parquet fixture result produced through the real vn.py CTA backtesting adapter.
- `backend_e2e_result.json`: full backend chain result with `report_id`, API paths, and report/trade/curve counts.
- `jm_real_smoke_backtest_result.json`: P0-005 real JM 5m/15m local standard Parquet smoke result.

The `output/` directory is ignored by Git except for `output/.gitignore`.

## Limits

- The demo script does not install vn.py or modify dependency files at runtime.
- This experiment does not call RQData directly.
- JM smoke mode reads only local standard Parquet and the local aggregate result JSON.
- Sample mode does not require real K-line data; it uses built-in sample bars.
- Fixture backtest mode uses the real vn.py CTA `BacktestingEngine`, but injects local sample bars directly and does not call `load_data()`.
- Backend E2E mode uses a temporary SQLite database by default and queries FastAPI endpoints in-process through `TestClient`.
- The standard Parquet fixture is synthetic research data, not a real RQData download and not a formal backtest conclusion.
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
provider
data_role
quality_status
symbol
contract
exchange
vt_symbol
datetime
trading_day
interval
period
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
source = rqdata / sample
provider = rqdata / local_parquet
```

## Next Steps

1. Use the Web report page to verify real reports, curves, and K-line markers.
2. Review backtest rigor before using any result outside research validation.
3. Decide whether the next backend smoke should use RQ worker execution against the local development PostgreSQL database.
