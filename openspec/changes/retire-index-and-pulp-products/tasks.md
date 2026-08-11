## 1. Universe configuration

- [x] 1.1 Keep `data/universe/active_products.txt` at exactly 60 unique codes (excluding retired)
- [x] 1.2 Keep `product_window_starts.csv` aligned with active (no retired rows)
- [x] 1.3 Keep `data/universe/retired_products.txt` with exactly nine lowercase codes: `br/cs/ic/if/ih/im/lu/nr/sp`

## 2. Hard rejection and retirement module

- [x] 2.1 Add `market_data/product_retirement.py` (load retired set, `assert_not_retired`, inventory/apply helpers)
- [x] 2.2 Wire exact-match guards into CLI product resolution and active-universe count check (60)
- [x] 2.3 Wire guards into HistoricalDataManager update/refresh and MetadataSynchronizer
- [x] 2.4 Filter retired symbols in MarketDataService series entry and `list_latest_dominants`

## 3. Retire-products CLI

- [x] 3.1 Register `guiyi data retire-products` with default dry-run and `--apply`
- [x] 3.2 Implement ordered DB hard delete + Canonical path purge with residual=0 report
- [x] 3.3 Ensure path deletes stay inside the configured canonical root

## 4. Docs and contracts

- [x] 4.1 Update STATUS / PROJECT_SOURCE / README / DATA_CENTER / GY-DATA-CORE-V2 and active converge OpenSpec to 60
- [x] 4.2 Add/update `docs/tasks/GY-DATA-PRODUCT-RETIREMENT-5.md` and register it in `docs/tasks/README.md`
- [x] 4.3 Record the decision in `DECISIONS.md`

## 5. Tests and verification

- [x] 5.1 Unit/CLI tests for universe 60, mutual exclusion, `PRODUCT_RETIRED`, and near-miss non-rejection
- [x] 5.2 Retire dry-run/apply fixture test reaching residual=0 while preserving non-retired rows
- [x] 5.3 Run directed `pytest` for data_foundation / CLI coverage

## 6. Production gate

- [x] 6.1 Dry-run against target env and report non-sensitive inventory
- [x] 6.2 After explicit one-shot intents: `--apply` for retired batches, verify residual=0, update STATUS/task fact
