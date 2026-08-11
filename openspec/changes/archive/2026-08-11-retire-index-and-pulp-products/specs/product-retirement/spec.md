## Purpose

Defines retirement of selected products from the active research universe: exact-match hard rejection, a 60-product active list mutually exclusive with retired codes, and an auditable dry-run/`--apply` purge of catalog rows and Canonical paths.

## ADDED Requirements

### Requirement: Active universe is 60 products excluding retired codes
The system SHALL treat `data/universe/active_products.txt` as the sole active product universe, containing exactly 60 unique lowercase product codes and MUST NOT include `br`, `cs`, `ic`, `if`, `ih`, `im`, `lu`, `nr`, or `sp`. The system SHALL keep `data/universe/retired_products.txt` as the retired exact-match list containing exactly those nine codes, mutually exclusive with the active list. Product window starts MUST omit retired codes.

#### Scenario: Active universe load validates count and exclusion
- **WHEN** the CLI loads `--universe active`
- **THEN** it returns exactly 60 unique codes and none of `br`/`cs`/`ic`/`if`/`ih`/`im`/`lu`/`nr`/`sp`

#### Scenario: Window starts omit retired products
- **WHEN** product window starts are loaded for maintenance planning
- **THEN** no row exists for `br`, `cs`, `ic`, `if`, `ih`, `im`, `lu`, `nr`, or `sp`

### Requirement: Exact-match hard rejection of retired products
The system SHALL reject any maintenance, metadata sync, or market series request whose product symbol normalizes (lowercase strip) to a retired code using exact membership only. Rejection MUST use the public error code `PRODUCT_RETIRED` and MUST fail closed without writing catalog or Canonical data for that symbol. Dominant/list surfaces MUST NOT present retired symbols once filtered or after purge.

#### Scenario: Explicit symbol update is rejected
- **WHEN** a caller requests `guiyi data update --symbol br` (or any other retired code)
- **THEN** the command fails with `PRODUCT_RETIRED` and performs no apply writes

#### Scenario: Metadata sync refuses retired instruments
- **WHEN** MetadataSynchronizer is asked to upsert metadata for a retired symbol
- **THEN** it fails with `PRODUCT_RETIRED` before upserting instrument/contract rows

#### Scenario: Near-miss codes are not rejected by retirement
- **WHEN** a caller requests an active product whose code is not an exact retired member
- **THEN** retirement rejection does not apply

### Requirement: Retire-products dry-run and apply purge
The system SHALL provide `guiyi data retire-products` that defaults to dry-run inventory of catalog rows and Canonical paths for retired symbols. With explicit `--apply`, it MUST hard-delete in order: `market_partitions` (via retired `market_datasets`), `market_datasets`, `main_contract_map`, `trading_sessions`, `contracts`, `instruments`, then remove Canonical directories under the configured canonical root for `symbol={retired}` after path normalization stays inside that root. It MUST NOT delete `exchanges` or `trading_calendars`. Missing rows or directories MUST be treated as successful no-ops. After apply, residual counts for retired symbols across those tables and paths MUST be zero. Production `--apply` MUST require a separate scoped one-shot execution intent outside the repository change itself.

#### Scenario: Dry-run reports inventory without mutation
- **WHEN** `guiyi data retire-products` runs without `--apply`
- **THEN** the result reports per-table row counts and path counts for retired symbols and leaves database and filesystem unchanged

#### Scenario: Apply reaches residual zero
- **WHEN** `guiyi data retire-products --apply` runs against an environment that contains retired-symbol catalog rows and/or Canonical directories
- **THEN** those rows and directories are removed in the required order and residual counts for the nine retired symbols are zero

#### Scenario: Shared exchange metadata is retained
- **WHEN** retire-products apply deletes retired instruments
- **THEN** `exchanges` and `trading_calendars` rows for shared exchanges remain
