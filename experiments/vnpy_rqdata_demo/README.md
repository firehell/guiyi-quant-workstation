# vn.py + RQData Local Parquet Demo

This directory is an experiment scaffold for validating the future V1 path:

```text
RQData
-> standard parquet
-> local config
-> vn.py CTA BacktestingEngine
-> normalized demo output
```

It is not part of the formal backend service, task queue, API, database schema, or Web workflow.

## Purpose

- Check whether the local workstation already has vn.py available.
- Keep a minimal config shape for reading local standard Parquet bars later.
- Provide a safe starting point for a future single-symbol, single-interval CTA backtest demo.
- Preserve the V1 boundary: research only, no live trading.

## Files

- `README.md`: experiment purpose, usage, limits, and next steps.
- `sample_config.json`: local-only sample config with placeholder Parquet paths and no credentials.
- `run_demo.py`: CLI entrypoint that supports `--help`, loads config, imports vn.py, and constructs one demo `BarData` object.

## Usage

Show CLI help:

```bash
python experiments/vnpy_rqdata_demo/run_demo.py --help
```

Run with the sample config:

```bash
python experiments/vnpy_rqdata_demo/run_demo.py \
  --config experiments/vnpy_rqdata_demo/sample_config.json
```

If vn.py is not installed, the command prints a clear message and exits without installing anything.

Verify the project environment can import vn.py:

```bash
uv run --project services/quant-api python -c "import vnpy; print(vnpy.__version__)"
```

Run the minimal object check in the project environment:

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py
```

## Limits

- The demo script does not install vn.py or modify dependency files at runtime.
- This experiment does not call RQData directly; it expects local standard Parquet data.
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

1. Add a small local fixture or point the sample config to a known standard Parquet slice.
2. Convert standard bar rows into vn.py `BarData` objects in this experiment only.
3. Extend the current `BarData` object check into a minimal vn.py CTA backtest if the dependency remains stable.
4. Convert raw vn.py statistics and trades into the Guiyi normalized result shape.
5. After external review (ChatGPT + docs/CODE_REVIEW.md), use the experiment findings to design `services/quant-api/app/vnpy_integration/`.
