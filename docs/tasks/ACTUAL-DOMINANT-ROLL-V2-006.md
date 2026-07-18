# ACTUAL-DOMINANT-ROLL-V2-006

生成时间：2026-07-18

状态：`COMPLETED / ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED`

## 1. 目标与 Stage 1 边界

本任务新增 actual rank=1 主力合约映射、换月、JM consumer coverage 与参数 lineage 的只读 Audit V2。固定 `audit_end=2026-07-10`。

Stage 1 只允许：

- 从 direct PostgreSQL 读取有界 `MainContractMap`、合约、交易日历、文件登记、quality 与交易参数证据；事务先执行 `SET TRANSACTION READ ONLY`。
- 读取 canonical/manifest/consumer source 以核验物理、checksum、DuckDB boundary 和语义一致性。
- 在一个全新 output directory 写本任务 CSV、Markdown 和 JSON 报告。

Stage 1 明确禁止：

- 不写 DB，不调用 ORM `add/delete/flush/commit`。
- 不写或覆盖 canonical Parquet、manifest、processed summary、quality、data role 或 Profile binding。
- 不导入或调用 RQData；不提供 repair/apply/overwrite 子命令。
- 不修改 Market、Backtest、Signal、live resolver 或参数解析器。
- 不把审计 residual 自动转成下载、重建或 metadata 修复。

## 2. 固定范围与语义

- Formal inventory 使用 canonical `data/universe/full_products_90.txt`，覆盖 90 品种的 `provider=rqdata / rule=volume_open_interest / rank=1` mapping 与 roll evidence。
- JM 是 V1-B 唯一 hard consumer；其他 89 品种 residual 保持 inventory evidence，不自动扩大为 consumer hard target。
- `.MAIN`、空合约、未登记真实合约、同日不同 actual contract 或不同 rule 均不得静默选择。
- 同合约多 version 全部保留为 evidence，仅按冻结顺序选择 effective row。
- Backtest/Review hard window：JM `1m + 1d`，`2023-06-28..2026-06-26`。
- Signal/live historical-reference hard window：JM `1m + 1d`，`2023-01-03..2026-07-10`。
- actual trigger 只能来自 confirmed actual-contract bar；连续主连价格不能冒充实际合约触发价。
- 旧审计的 actual 固定 `45` 仅是历史审计模型快照，不进入本任务代码、测试、fixture、统计、Gate 或 repair 数量。

## 3. CLI 契约

唯一子命令：

```text
verify
  --project-root PATH
  --audit-end 2026-07-10
  --scan-mode quick|full
  --products-file data/universe/full_products_90.txt
  --product PRODUCT          # 可重复，只允许 smoke
  --max-workers 4
  --output-dir PATH
```

规则：

- `--products-file` 必须解析为 `<project-root>/data/universe/full_products_90.txt`；CLI 不自行加载另一份品种池，formal unfiltered scope 由 service 读取固定文件。
- 相对 `--output-dir` 归一化后必须仍位于 project root 内；`../escaped` 在 DB/report access 前 fail-closed。绝对目录（例如 `/tmp` smoke）按冻结契约允许。已有目录或 writer race collision 均 fail-closed，不支持 overwrite。
- CLI 加载 `<project-root>/.env`，但不输出凭据；随后使用 direct `SessionLocal`。
- CLI 只调用 `run_actual_dominant_roll_audit()` 和 `write_actual_dominant_roll_reports()`。
- repeated `--product` 只形成 filtered smoke；service 的 filtered 结果不得产生 formal Ready。
- invalid date/choice/缺失参数不输出 argparse usage，只返回单行 `INVALID_ARGUMENTS` compact JSON 与 exit 2。
- stdout/stderr 每次只输出一个 compact JSON；错误文本中的原始 `DATABASE_URL`、`postgresql+psycopg` 规范化 URL 和 URL password 均脱敏。

Exit code：

| exit | 状态 |
|---:|---|
| 0 | 仅 `ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED` |
| 2 | invalid arguments/output path/products-file、环境、DB 或未知 audit 阻塞 |
| 3 | `OUTPUT_EXISTS` |
| 4 | `ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED`，包括 filtered smoke |

compact JSON 至少包含 `status`、`output_directory`、`counts`、`db_snapshot_source`、`outputs`（报告已 dispatch 时）以及：

```text
writes_database=false
writes_parquet=false
writes_manifest=false
writes_quality=false
calls_provider_api=false
calls_rqdata=false
```

## 4. 报告与 schema

输出固定为八个文件：

| 文件 | 固定核心字段 / 结构 |
|---|---|
| `rank1_uniqueness.csv` | `product, trade_date, contract, version, provider, rule, rank, id, registered, mapping_count, status, selection, selection_reason` |
| `rank1_ranges.csv` | `product, contract, start_date, end_date, mapping_days, provider_start_date, provider_boundary_status, provider_boundary_source, provider_start_inferred_from_physical` |
| `actual_target_coverage.csv` | `consumer, profile, product, contract, period, start_date, end_date, expected_trading_day_count, calendar_status, physical_status, manifest_status, database_status, quality_status, checksum_status, duckdb_status, boundary_status, boundary_evidence, missing_trading_dates, normalized_path_count, manifest_overlap_count, physical_only_count, db_only_count, mapping_semantics, status, path_evidence` |
| `roll_transition_audit.csv` | `product, previous_contract, contract, previous_mapping_date, roll_date, classification, boundary_status, calendar_contiguous, previous_close, current_open, price_difference, price_difference_status` |
| `trading_parameter_lineage.csv` | `product, trade_date, contract, field, value, source, source_row_id, data_version, effective_start, effective_end, complete` |
| `actual_residuals.csv` | `residual_id, category, scope, product, consumer, period, contract, trade_date, target_start, target_end, root_cause, recommended_repair, write_requirements, risk` |
| `ACTUAL_DOMINANT_ROLL_SUMMARY.md` | audit summary JSON，包括 scope/counts/formal eligibility/consumer semantics/只读 flags |
| `audit_evidence.json` | `{summary, evidence}`，记录 required reports、provider/rule/rank、scope 与 consumer semantic checks |

空 CSV 也必须保留稳定 header；output directory 通过同文件系统 staging 原子落位，失败后清理 staging。

## 5. Formal Gate

只有以下条件全部成立，service 才可返回 `ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED`：

1. `scan_mode=full`、没有 `--product` filter、canonical 90-product scope 完整。
2. direct PostgreSQL 可用并成功设置 read-only transaction。
3. JM hard mapping/calendar/provider boundary 完整，无不同 contract/rule conflict、无缺失 mapping trading date。
4. JM 四个 consumer-period targets 的 physical、manifest、DB、quality、checksum、DuckDB、boundary 全部通过。
5. JM 每个实际合约交易参数按 exact parameter、contract/product fee rule、contract multiplier fallback 的冻结优先级完整，并保留 per-field lineage。
6. historical/live rank1 resolver 语义一致，参数 precedence 一致，actual-confirmed trigger 语义通过。
7. 没有 `scope=jm_hard` 或 `scope=formal` residual。

90 品种 inventory residual 可保留为后续证据，但不能绕过 canonical scope 或 JM/formal blocker。quick、filtered、非 PostgreSQL 或任何 hard/formal residual 一律返回 `ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED` 或环境阻塞，不能宣称 Ready。

## 6. Residual / repair 分类

本任务只分类，不执行 repair：

- mapping：产品/日期缺失、provider boundary、不同 contract/rule conflict、invalid actual contract、mapping semantics。
- calendar：JM hard window boundary 或 mapping trading-date gap。
- target coverage：physical、manifest、DB、quality、checksum、DuckDB、1m/1d boundary 的精确失败层。
- roll transition：mapping gap、backward-month、A-B-A reversal；price difference 仅 informational。
- trading parameter：exact/fee/contract fallback 后仍缺字段或 lineage 不完整。
- consumer semantics：historical/live mapping、actual-confirmed trigger、historical/live parameter precedence 不一致。

任何后续 repair 必须另开任务，基于 `actual_residuals.csv` 冻结精确 ledger、写边界与 rollback；不得沿用旧 `45` 生成批次。

## 7. 精确运行命令

JM quick smoke（只产生 smoke evidence，不可能 formal Ready）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/rqdata_actual_dominant_roll_audit_v2.py verify \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --audit-end 2026-07-10 \
  --scan-mode quick \
  --products-file data/universe/full_products_90.txt \
  --product jm \
  --max-workers 4 \
  --output-dir /tmp/actual_dominant_roll_006_jm_smoke_001
```

90-product formal full（已执行，报告目录禁止覆盖）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/rqdata_actual_dominant_roll_audit_v2.py verify \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --audit-end 2026-07-10 \
  --scan-mode full \
  --products-file data/universe/full_products_90.txt \
  --max-workers 4 \
  --output-dir data/reports/full_history_audit_v2_20260710/actual_dominant_roll_006
```

代码验证：

```bash
cd services/quant-api
.venv/bin/pytest -q tests/test_actual_dominant_roll_audit_cli.py
.venv/bin/ruff check ../../scripts/rqdata_actual_dominant_roll_audit_v2.py tests/test_actual_dominant_roll_audit_cli.py
cd ../..
git diff --check
```

## 8. 实际执行与当前 Gate

```text
status=ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED
audit_end=2026-07-10
product_count=90
rank1_mapping_count=287597
rank1_singleton_evidence_rows=173261
rank1_effective_selection_rows=230429
rank1_duplicate_same_contract_rows=114336
rank1_different_contract_conflicts=0
parameter_scope=jm_hard_consumer_window
parameter_mapping_day_count=840
parameter_lineage_rows=5880
parameter_incomplete_rows=0
hard_jm_residual_count=35
formal_residual_count=3
inventory_residual_count=1054
mapping_date_missing_jm=11
target_coverage_residuals_jm=24
db_snapshot_source=direct_postgresql
writes_database=false
writes_parquet=false
writes_manifest=false
calls_rqdata=false
```

JM quick 与 canonical 90-product full 已在 Mac mini 实际外置盘和 direct PostgreSQL 完成。第一次 full 因错误地为 90 品种全部 mapping day 生成参数 lineage 而在只读事务中人工中止；中止后相关五张 DB 表计数与运行前完全一致，正式 output/staging 均不存在。参数 scope 修正为 JM hard consumer window 后，正式 full 在约 34 秒完成。

正式报告位于：

```text
data/reports/full_history_audit_v2_20260710/actual_dominant_roll_006/
```

44 条 target-range coverage 中 20 条全部分层通过；19 条缺 manifest evidence，5 条存在 manifest overlap。physical、DuckDB readability 与 actual SHA 内容层均通过，交易参数 840 个 JM mapping day / 5880 个 per-field lineage row 全部完整。Gate 仍被 11 个 JM mapping 缺日、24 个 coverage residual 和 3 个 consumer semantic mismatch 阻断，因此当前不得写 `ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED`。

Stage 1 没有执行任何 repair。后续必须从本次 `actual_residuals.csv` 分别冻结 resolver semantics、mapping metadata、actual registration/manifest 与 trading parameter dry-run ledger；任何写入仍需独立批准。
