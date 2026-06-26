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
- `run_demo.py`: CLI entrypoint that supports `--help`, loads config, and fails clearly if vn.py is not installed.

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

## Limits

- This experiment does not install vn.py or modify dependency files.
- This experiment does not call RQData directly; it expects local standard Parquet data.
- This experiment does not call TqSdk, CTP, broker gateways, or trading interfaces.
- This experiment does not read or write accounts, passwords, tokens, licenses, or API keys.
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
3. Run a minimal vn.py CTA backtest if vn.py is already installed locally.
4. Convert raw vn.py statistics and trades into the Guiyi normalized result shape.
5. After Claude Code review, use the experiment findings to design `services/quant-api/app/vnpy_integration/`.
