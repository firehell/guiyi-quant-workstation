# Scoped Data Audit Design

## Purpose

Allow one active product to pass through the same read-only Canonical audit used
for the active universe. This creates a repeatable per-product acceptance gate
for DFD-07 rebuild waves without adding a second audit service or operator
script.

## Scope

The public CLI becomes:

```text
guiyi data audit (--symbol X | --universe active)
```

`--symbol` and `--universe active` are required and mutually exclusive. A
symbol is normalized and checked against the retired-product list using the
existing `_products()` helper. The request builder creates `AuditRequest` from
the selected tuple, and `HistoricalDataManager.audit()` remains the only audit
implementation.

The command remains read-only: it does not synchronize metadata, request
RQData, write PostgreSQL, or write Canonical Parquet.

## Implementation Boundaries

Allowed changes are limited to:

- `services/quant-api/app/guiyi_cli/data_parser.py`
- `services/quant-api/app/guiyi_cli/data_commands.py`
- targeted CLI tests
- `docs/DATA_CENTER.md`, `TESTING.md`, and the active OpenSpec CLI contract

The change does not modify `HistoricalDataManager`, Catalog, storage, data
schemas, active universe files, Runtime, live observation, notifications, or
order behavior.

## Error Handling

- Supplying both selectors or neither is a JSON CLI argument error.
- A retired symbol is rejected by the existing retired-product guard.
- An audit finding remains a normal read-only audit result; this change does
  not reinterpret, suppress, or repair any finding.

## Tests

Test-first coverage proves that:

1. `audit --symbol jm` creates a one-product `AuditRequest` and invokes the
   existing manager audit method.
2. `audit --universe active` keeps its existing behavior.
3. selector omission and selector conflict are rejected.
4. a retired symbol is rejected before a manager call.

Existing maintenance tests remain the evidence that `AuditRequest` itself is
read-only and reports missing partitions correctly.

## Read-only Canary Preflight

After the repository change passes local verification, run a production
read-only preflight at fixed `T0=2026-08-07`:

1. Read the production revision, Canonical root, active-universe count, and
   J/JM partition baseline without exposing credentials.
2. Read the Catalog to select one incomplete, non-J/JM active product from
   each of CZCE, SHFE, INE, and GFEX. Select the alphabetically first eligible
   symbol in each exchange so the choice is reproducible.
3. Run universe audit to capture its first fail-closed blocker.
4. For each selected symbol, run scoped audit and `data update --symbol X
   --through 2026-08-07` without `--apply`.

The preflight records observed failures such as missing sessions or metadata
as blockers only. It does not call RQData or write production Catalog or
Parquet, and it does not authorize a later `--apply`.

## Acceptance Criteria

- Both audit selectors produce the correct `AuditRequest`.
- Invalid selectors and retired symbols are rejected with existing CLI error
  behavior.
- Targeted tests and data-foundation CLI tests pass.
- Documentation and the active OpenSpec contract show the same audit syntax.
- The canary preflight is demonstrably read-only and reports an exact selected
  symbol and observed result for each of the four exchanges.
