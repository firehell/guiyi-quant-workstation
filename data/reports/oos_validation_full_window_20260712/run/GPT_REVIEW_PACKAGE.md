# GPT Review Package: JM V1B OOS Full Window

## Frozen Config
- baseline_report_id: 14
- strategy: {'strategy_code': 'jm_v1b_daily_direction_fast_entry', 'strategy_version': 'v1b.0', 'entry_interval': '15m', 'strategy_class_path': 'guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.vnpy_strategy.JmV1bDailyDirectionFastEntryStrategy'}
- data_policy: {'data_source': 'local_parquet', 'data_role': 'primary', 'quality_status': 'passed', 'execution_timing': 'next_bar_open'}
- costs: {'rate': 0.0001, 'slippage': 1.0, 'size': 60, 'pricetick': 0.5, 'capital': 100000.0}
- persist_to_db: False

## Execution Commands
```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/oos_validation_run.py \
  --run --format markdown --output-dir <output_dir>
```

## Overall Status
- overall_status: passed
- readonly: False
- would_write_db: False

## Window Results
### in_sample_baseline (success)
- metrics: trades=125, return_pct=-8.558892370374481, mdd_pct=0.14193044466174673, win_rate=0.408, profit_factor=0.8634589704358555
- trust_audit_status: passed

### oos_fixed (success)
- metrics: trades=32, return_pct=-9.060590093390609, mdd_pct=0.07610456501871173, win_rate=0.375, profit_factor=0.2863759349859278
- trust_audit_status: passed

### walk_forward_a_test (success)
- metrics: trades=5, return_pct=-1.9195061827770694, mdd_pct=0.015422367778392072, win_rate=0.0, profit_factor=0.0
- trust_audit_status: passed

### walk_forward_b_test (success)
- metrics: trades=14, return_pct=0.5460049240210938, mdd_pct=0.02717189320996609, win_rate=0.35714285714285715, profit_factor=1.0836909455585115
- trust_audit_status: passed

### walk_forward_c_test (success)
- metrics: trades=32, return_pct=-9.060590093390609, mdd_pct=0.07610456501871173, win_rate=0.375, profit_factor=0.2863759349859278
- trust_audit_status: passed

## Baseline vs OOS

- in_sample_baseline: delta_return_pct=10.726638639477008
- oos_fixed: delta_return_pct=10.22494091646088
- walk_forward_a_test: delta_return_pct=17.36602482707442
- walk_forward_b_test: delta_return_pct=19.831535933872583
- walk_forward_c_test: delta_return_pct=10.22494091646088

## Risks and Boundaries
- Trust passed on report 14 does not imply strategy profitability or live readiness.
- OOS losses and drawdown expansion must be preserved; no parameter tuning was applied.
- OOS runs do not write formal backtest reports to PostgreSQL.
- Walk-forward windows are test-only slices; train windows are metadata only in this CLI.

## Review Questions for External GPT
1. Are trade/order/equity/fee checks sufficient for non-DB OOS evidence?
2. Do OOS deteriorations look like regime shift rather than implementation drift?
3. Should any window be blocked from further research despite frozen parameters?