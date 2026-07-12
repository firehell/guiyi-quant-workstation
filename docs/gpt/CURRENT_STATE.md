# 当前项目状态

更新时间：2026-07-12

用途：浏览器 GPT 当前事实速览。代码、数据库和审计产物优先于历史聊天。

## 当前阶段

```text
V1-TRUSTED-CLOSURE
→ TASK-2026-07-11-001-data-asset-audit DELIVERY_READY_WITH_CLI_ENV_NOTE
→ WEB-VISUAL-REFACTOR-V1B DELIVERY_READY
→ WEB-MAIN-INDICATORS-V1 DELIVERY_READY
→ DATA-TARGET-COVERAGE-AUDIT MERGED_TO_MAIN
→ TARGET-COVERAGE-GAP-TRIAGE DELIVERY_READY_READONLY_TRIAGE
→ AD-EC-OP-WEEKLY-ROW-COUNT-RECONCILE DELIVERY_READY_READONLY_RECONCILE
→ AD-EC-OP-WEEKLY-METADATA-ROW-COUNT-REPAIR DELIVERY_READY_METADATA_REPAIR
→ RESIDUAL-DATA-RISK-DISPOSITION DELIVERY_READY_RISK_DISPOSITION
→ SOURCE-INTERVAL-PROVENANCE-REPAIR-DRY-RUN DELIVERY_READY_DRY_RUN
→ SOURCE-INTERVAL-PROVENANCE-REPAIR-APPLY DELIVERY_READY_APPLY_COMPLETED
→ LPV-ACTUAL-CONTRACT-REGISTRATION-DRY-RUN DELIVERY_READY_DRY_RUN_NO_DB_WRITE
→ RESIDUAL-DATA-RISK-CLOSEOUT-DRY-RUN DELIVERY_READY_DRY_RUN_NO_WRITE
→ REFERENCE-METADATA-GAP-APPLY-PLAN DELIVERY_READY_APPLY_PLAN_NO_WRITE
```

当前结论：

- Stage 13-G 已完成，`report_id=14` trust audit 为 `passed`。
- JM 最新主连 `1m/5m/15m/30m/60m/1d` 六周期为 `20230103_20260711_v2 / primary / passed`。
- 5m/15m/30m/60m/1d 均从最新 passed 1m standard parquet 本地聚合，`source_interval=1m`。
- Stage 8.6 全品种 `1d` Gate 当前 data-audit snapshot：82 products passed、8 partial；1326 manifest-level discovered active records passed、8 pending。
- JM 最新主连六周期专用 Gate：6/6 active passed。
- 数据盘点 direct CLI 已尝试，但 data-audit worktree 无 `.env` / `DATABASE_URL`，默认无密码 DB 连接失败；主工程复跑使用 `database` 口径。
- 新目标覆盖矩阵审计已从 data-audit worktree 合并回 main；只能验收为 `目标覆盖矩阵只读审计完成`，不能验收为 `数据修复完成`。
- 目标覆盖缺口只读 triage 已完成；只能验收为 `缺口根因分类完成`，不能验收为 `DB 登记 / Parquet 修复 / 质量状态修复完成`。
- `ad/ec/op` 周线 row_count 只读对账已完成；旧版本 metadata stale 证据已确认。
- `ad/ec/op` 周线 metadata row_count 受控修复已完成；仅更新 3 条 `market_data_files.row_count`，未写 Parquet/manifest/checksum/RQData/质量状态。
- 剩余数据风险已完成受控分流：`source_interval_unverified`、`missing_db_registration`、`quality_failed`、参考元数据缺口和工作区外部变更均有明确 Gate，不再作为散落未处理项。
- `source_interval_provenance_repair_apply` 已完成：276 个 candidates 已补 `source_interval=1m`，同步 Parquet checksum、manifest checksum、DB `market_data_files.checksum/file_size_bytes`，其中 61 个已有 processed summary 同步 checksum；`source_interval_unverified` 已清零。
- `missing_db_registration` dry-run 已完成：108 target rows 对应 93 unique paths，87 个已有唯一登记，6 个为 `L2609F` 同路径多版本，真实 eligible=0。根因是 `l_f/pp_f/v_f` manifest 产品名解析误报，本轮不写 DB。
- residual data risk closeout 已完成：105 条 `quality_failed` 去重为 15 个文件，全部为 stale processed summary 误报；target coverage 复跑后 `quality_failed=0`，转为 `quality_warning=105`，`covered_passed` 仍为 17203。
- `L2609F` 六条同路径多版本已输出治理候选报告；本轮未删除、归档、合并或修改任何历史 DB 行。
- reference metadata gaps 已输出 dry-run 候选：285 `needs_contract_universe_sync`、546 `needs_continuous_contract_sync`；后续 apply 必须另开 metadata-only 人工 Gate。
- reference metadata gap apply plan 已完成 no-write 计划化：831 个 candidate rows 拆成 11 个 dataset/year batches；本轮只生成命令清单，不调用 RQData、不写 DB。
- PostgreSQL、Redis 仅绑定 localhost；Redis 已启用环境变量密码。
- 公网保留腾讯云 Nginx + FRP 拓扑，已收敛为 HTTPS + Basic Auth；Mac mini 侧由 launchd 监督 static/API/workers，但尚未完成真实 TLS/防火墙/隧道/重启 smoke。
- 2026-07-12 重启后健康检查：`Docker AutoStart` 已开启；`./scripts/post-reboot-verify.sh` 全部通过（API/Web/runtime_health/postgres/redis）。
- launchd 长期运行副本确认为 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate`（`codex/jm-live-runtime-gate`）；`guiyi-quant-workstation` 仅作开发/只读验收，不重绑 launchd。
- 重启根因：Docker Desktop 未随登录自启会导致 PG/Redis 短暂不可用；Worker 在 Redis 恢复后由 KeepAlive 自愈。

## 主链路

```text
RQData 1m -> standard 1m quality passed
-> local aggregation -> manifest/checksum/DB metadata
-> DuckDB -> vn.py/FastAPI -> Web/Report/Review/Signal
```

active 入口：

```text
provider in (rqdata, local_parquet)
data_role = primary
quality_status != failed
```

严格研究使用 `quality_status=passed`。

## JM 数据

| period | rows | max datetime | derivation |
|---|---:|---|---|
| 1m | 290715 | 2026-07-10 15:00 | RQData direct |
| 5m | 58143 | 2026-07-10 15:00 | aggregated from 1m |
| 15m | 19381 | 2026-07-10 15:00 | aggregated from 1m |
| 30m | 10116 | 2026-07-10 15:00 | aggregated from 1m |
| 60m | 5909 | 2026-07-10 15:00 | aggregated from 1m |
| 1d | 851 | 2026-07-10 00:00 | trading_day aggregation from 1m |

## 数据资产盘点

- Stage 8.6 快照任务：`TASK-2026-07-11-001-data-asset-audit`
- Stage 8.6 报告目录：`data/reports/data_audit_20260711/`
- direct CLI 状态：data-audit worktree 因无 DB 认证环境失败；主工程 fallback 使用 `database` 口径。
- 产品层结论：82 `active_passed` / 8 `active_partial`。
- 当前 snapshot 资产口径：1326 `active_passed` / 8 `audit_pending`，仅表示 manifest-level discovered active records；唯一键限定为 `product + asset_scope + contract + period + standard_path`。
- `1326` 构成：`actual_contract` 1241 passed / 3 pending，`dominant_main` 85 passed / 5 pending；当前 profile 全部为 `1d`，不是多周期全量覆盖。
- DuckDB row count 和 datetime boundary 已核对；checksum 未在本报告中逐文件独立证明。
- 8 pending 不阻塞 JM V1-B；JM 最新主连六周期仍为 6/6 `active_passed`。
- Stage 9 仍为 90 `stage9_blocked`，本任务不授权企业微信发送。

## 目标覆盖矩阵审计

- 任务：`TASK-2026-07-11-002-data-target-coverage-audit`
- data-audit 提交：`fd881bac`
- 主工程承接分支：`codex/data-target-coverage-audit-main`
- 修复前报告目录：`data/reports/target_coverage_audit_20260711/`
- 修复后报告目录：`data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`
- 已带入目标覆盖审计 CLI、服务模块、测试、任务单和 6 个报告产物。
- 后续数据审计、DB/API/parquet 覆盖矩阵工作只在主工程 `/Volumes/扩展盘/guiyi-quant-workstation` 继续，不再在 `/Volumes/扩展盘/guiyi-parallel/data-audit` 增量执行。
- 主工程已复跑 `scripts/rqdata_target_coverage_audit.py`，报告记录 `db_snapshot_source=database`。
- 修复前主工程复跑结果：17689 target rows、15164 physical inventory rows、2091 issue rows。
- 修复后主工程复跑结果：17689 target rows、15164 physical inventory rows、2083 issue rows。
- 修复后覆盖矩阵状态：16164 `covered_passed` / 1039 `covered_warning` / 108 `missing_db_registration` / 105 `metadata_gap` / 273 `not_applicable`。
- 元数据矩阵状态：2445 `covered_passed` / 831 `metadata_gap` / 504 `not_applicable`。
- source_interval provenance full apply 后主要 issue：546 `missing_continuous_contract_map`、285 `missing_contract_universe`、108 `missing_db_registration`、105 `quality_failed`。
- `row_count_mismatch` 已因 3 条旧版本周线 DB metadata row_count 受控修复而清零。
- `missing_db_registration=0`；`quality_failed=0`；剩余需规划的是 reference metadata gaps 的 metadata-only sync/apply Gate，以及 105 条 `quality_warning` 的人工理解和策略使用边界。
- reference metadata gap apply plan 已生成：831 candidate rows、11 batches；状态仍是 no-write plan，不代表 reference metadata 已补齐。

## 目标覆盖缺口只读 triage

- 任务：`TASK-2026-07-11-005-target-coverage-gap-triage`
- 报告目录：`data/reports/target_coverage_gap_triage_20260711/`
- 本轮只读取既有审计 CSV 和本地 Parquet；未写 DB、未写 Parquet、未调用 RQData、未改 Alembic。
- `source_interval_unverified`：1039 target rows、276 unique Parquet files；复核结果均为 `source_interval_column_missing`。当前应归类为派生资产 provenance metadata column gap，不能直接当作 OHLCV 数据损坏。
- `row_count_mismatch`：8 target rows 映射到 3 个周线主连文件：`ad.MAIN`、`ec.MAIN`、`op.MAIN`。DuckDB 实读行数分别比 DB/manifest row_count 多 8、14、6 行，duplicate datetime 均为 0；下一步优先核对 DB/manifest row_count 是否旧或不完整。
- `missing_db_registration`：108 target rows，`l` 46、`pp` 31、`v` 31；当前仅产出 candidate-only 清单，不执行 DB 写入。
- `quality_failed`：历史 triage 中为 105 target rows；已在 TASK-007 证实为 stale processed summary 误报，当前 target coverage 为 105 条 `quality_warning`。
- metadata gaps：831 rows，其中 `missing_continuous_contract_map` 546、`missing_contract_universe` 285。

## AD/EC/OP 周线 row_count 只读对账

- 任务：`TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile`
- 报告目录：`data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/`
- 本轮只读取既有审计 CSV、manifest、processed summary、canonical Parquet 和 PostgreSQL `market_data_files` snapshot；未写 DB、未写 Parquet、未调用 RQData、未改 Alembic。
- DB 只读连接状态：`available`。
- `20260707` 旧版本周线文件：
  - `ad.MAIN`：DB row_count 47，manifest / processed summary / DuckDB 均为 55，分类 `old_version_metadata_stale`。
  - `ec.MAIN`：DB row_count 134，manifest / processed summary / DuckDB 均为 148，分类 `old_version_metadata_stale`。
  - `op.MAIN`：DB row_count 36，manifest / processed summary / DuckDB 均为 42，分类 `old_version_metadata_stale`。
- `duplicate_datetime_count=0`；`20260710` / `20260711` 后续 sibling 文件共 6 条均为 `matched`。
- 本轮不支持“Parquet 需要重建”的结论；若要消除旧 mismatch，需另开受控 metadata 修复 Plan。

## AD/EC/OP 周线 metadata row_count 受控修复

- 任务：`TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair`
- 修复报告目录：`data/reports/ad_ec_op_weekly_metadata_repair_20260712/`
- 修复后对账目录：`data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/`
- 修复后目标覆盖目录：`data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`
- dry-run：`ready_to_apply=True`。
- apply：`writes_database=True`。
- 仅更新 3 条 `market_data_files.row_count`：
  - `ad` / `db_file_id=44115`：47 -> 55。
  - `ec` / `db_file_id=44133`：134 -> 148。
  - `op` / `db_file_id=44159`：36 -> 42。
- 修复后周线对账：9 条全部 `matched`。
- 修复后目标覆盖矩阵：`row_count_mismatch` 清零，`issue_register_rows=2083`。
- 未写 Parquet、manifest、checksum、data_version、data_role、quality_status；未调用 RQData；未授权 Stage 9。

## 剩余数据风险受控分流

- 任务：`TASK-2026-07-12-003-residual-data-risk-disposition`
- 报告目录：`data/reports/residual_data_risk_disposition_20260712/`
- 本轮不写 DB、不写 Parquet、不改质量状态、不调用 RQData。
- `source_interval_unverified`：1039 rows / 276 unique Parquet files；归入 `source_interval_provenance_repair_dry_run`，若后续重写 Parquet 添加 `source_interval=1m`，必须同步 checksum、manifest、processed summary 和 DB checksum。
- `missing_db_registration`：108 rows / 93 unique files，产品 `l/pp/v`；归入 `lpv_actual_contract_registration_dry_run`，人工确认后才允许 DB 写入。
- `quality_failed`：105 rows / 15 unique files；已由 `TASK-2026-07-12-007` 确认为 stale processed summary 误报，当前为 `quality_warning=105`，禁止为覆盖率改成 passed。
- 参考元数据缺口：`missing_continuous_contract_map=546`、`missing_contract_universe=285`；归入 `reference_metadata_gap_dry_run`，不让 Market / Backtest / Signal / Review 各自补 fallback。
- 工作区外部变更：当前 `git status --short` 未显示 `README.md`、`scripts/local-services-status.sh`、`scripts/post-reboot-verify.sh` 为活动变更；若后续再次出现，另开 runtime/local-workstation checkpoint，不与数据修复混做。
- 推荐下一步：先做 `source_interval_provenance_repair_dry_run`。

## source_interval provenance repair dry-run

- 任务：`TASK-2026-07-12-004-source-interval-provenance-repair-dry-run`
- 报告目录：`data/reports/source_interval_provenance_repair_dry_run_20260712/`
- 本轮只读取 target coverage issue register、source interval triage、manifest、processed summary 和 canonical Parquet schema/统计；未写 DB、未写 Parquet、未改 manifest、未改 processed summary、未调用 RQData。
- 输出：
  - `candidate_files.csv`：276 unique Parquet file candidates。
  - `affected_coverage_rows.csv`：1039 target coverage row mappings。
  - `SOURCE_INTERVAL_PROVENANCE_REPAIR_DRY_RUN.md`：dry-run 汇总和 apply Gate。
- 候选周期分布：`1d=80`、`5m=49`、`15m=49`、`30m=49`、`60m=49`。
- 276 个 candidate 全部为 `source_interval_column_missing`，全部 `apply_eligible=True`。
- 276 个 candidate 均需要同步 manifest checksum 和 DB `market_data_files.checksum`；其中 61 个有 processed summary 记录需要同步，215 个没有对应 processed summary 记录。
- 后续若进入 apply，必须另开受控写入任务并再次人工确认；apply 只允许围绕 `source_interval=1m` provenance 和 checksum/file_size 同步，不得顺手修改质量状态、DB registration、failed quality 或 reference metadata。

## source_interval provenance repair apply

- 任务：`TASK-2026-07-12-005-source-interval-provenance-repair-apply`
- Pilot apply 目录：`data/reports/source_interval_provenance_repair_apply_pilot_20260712/`
- Full apply 目录：`data/reports/source_interval_provenance_repair_apply_full_20260712/`
- Full 后 dry-run 目录：`data/reports/source_interval_provenance_repair_dry_run_after_full_20260712/`
- Full 后 target coverage 目录：`data/reports/target_coverage_audit_20260712_after_source_interval_full/`
- Pilot apply：5 selected / 5 applied / 0 blocked；pilot 后 `source_interval_unverified` 1039 -> 1019。
- Full apply：276 selected / 271 applied / 5 skipped / 0 blocked；5 skipped 是 pilot 已处理文件。
- Full apply 写入：Parquet=True、manifest=True、DB=True、processed summary=True；processed summary updates=61。
- Full 后 dry-run：276 files 均为 `already_source_interval_1m`，manifest checksum 276 matched，processed summary checksum 61 matched / 215 not_found。
- Full 后 target coverage：`source_interval_unverified` 已清零，issue_register_rows=1044，covered_passed=17203。
- 本任务未调用 RQData，未新增 schema/migration，未修改 `row_count`、`data_version`、`data_role`、`quality_status`，未处理 `missing_db_registration`、`quality_failed` 或 reference metadata gaps。

## 回测可信基线

- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- trades：155 mapped
- orders：239 mapped
- audit checks：10/10 passed
- total return：约 -19.29%

该结果只能说明可追溯和内部一致，不能说明策略有效或可实盘。后续只做样本外验证设计，不调参改善收益。

## 功能状态

- Data / Market / Backtest / Signal / Review / Runtime：代码与 API 已形成 V1 研究闭环。
- Web 视觉：已完成克制科技感设计系统、四组导航、真实 Dashboard 指标、Signal 宽表和 K 线 1440/1280/1024 响应式；11 路由 browser smoke 无 console error/warning。
- Web 主图指标：`EMA10` / `EMA21` / `EMA60` / `火天大有` 多选叠加已完成；`EMA21` 默认可见，`MACD` 固定副图。
- 企业微信：preview、单条受控发送和通知记录已完成；没有自动 scheduler。
- live：ingest/aggregation/evaluator 代码存在；没有长期 scheduler，live tables/checkpoints 不代表正在运行。
- 自动交易、实盘账户、委托接口：未实现且禁止扩展。

## 当前风险

- 全品种 Stage 8.6 pending：`bb/rs/wh/wr/zc` quality warning；`L2609F/PP2609F/V2609F` 缺 DB 登记。它们只是当前 `stage8_6_1d_first` profile 的问题，不代表完整目标覆盖缺口全集。
- 目标覆盖矩阵中的 `source_interval_unverified` 已通过受控 apply 清零；该结论只覆盖 provenance metadata 和 checksum/file_size 同步，不外推到 DB registration、quality failed 或 reference metadata gaps。
- `row_count_mismatch` 已通过 `ad/ec/op` 三条旧版本周线 DB metadata row_count 受控修复清零；不得把该结论外推到 provenance、missing registration 或 quality failed/warning。
- `missing_db_registration` dry-run 已证实无真实新增候选；人工 Gate 结论为不需要且不授权 DB 写入。`L2609F` 六条同路径多版本仅作风险记录。
- `quality_failed` 根因审查已完成；不得把 105 条 `quality_warning` 升级为 passed，也不得直接修改质量状态来提高覆盖率。
- 剩余风险已归入三个 Gate；后续不要跨 Gate 混写 DB registration、质量状态和参考元数据。
- `TASK-2026-07-12-007-residual-data-risk-closeout-dry-run` 已完成只读 closeout：
  - 105 条 `quality_failed` 去重为 15 个文件，全部为 `stale_processed_summary_failed`。
  - 当前 DB、manifest、quality report 均为 `warning`；stale `processed_summary=failed` 不再覆盖 active warning。
  - target coverage 复跑后 `quality_failed=0`，转为 `quality_warning=105`，`covered_passed` 仍为 17203。
  - `L2609F` 六条同路径多版本仅输出 current/superseded 对照，不写 DB。
  - reference metadata gaps 仍为 831：285 `needs_contract_universe_sync`、546 `needs_continuous_contract_sync`。
  - 后续 reference metadata apply 必须另开人工 Gate，不得在 Market/Backtest/Signal/Review 各自补 fallback。
- `TASK-2026-07-12-008-reference-metadata-gap-apply-plan` 已完成 no-write apply plan：
  - 输入 TASK-007 reference metadata gap ledger。
  - 831 条 gap 全部转为 apply candidate rows。
  - 分成 11 个 dataset/year batches：`contract_universe` 2020-2023；`continuous_contract_map` 2020-2026。
  - 只生成 `apply_candidate_rows.csv`、`apply_batches.csv` 和 Markdown plan。
  - `writes_database=False`、`writes_parquet=False`、`writes_manifest=False`、`calls_rqdata=False`。
  - 任何真实 RQData 调用或 PostgreSQL metadata write 仍必须另开人工 Gate。
- 真实公网 TLS、Basic Auth、端口封闭和 systemd restart 尚需服务器现场验证。
- macOS 外接卷后台访问需人工授权或迁移运行副本。
- 样本外验证未完成。

## 当前任务与事实源

- `tasks/current.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/TASK-2026-07-11-002-data-target-coverage-audit.md`
- `docs/tasks/TASK-2026-07-11-003-web-main-indicators.md`
- `docs/tasks/TASK-2026-07-11-005-target-coverage-gap-triage.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `data/reports/stage8_6_active_gate_summary.md`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
- `data/reports/data_audit_20260711/DATA_ASSET_INVENTORY.md`
- `data/reports/data_audit_20260711/stage8_6_active_gate_summary.md`
- `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
- `data/reports/target_coverage_audit_20260711/coverage_summary.md`
- `data/reports/target_coverage_audit_20260711/target_coverage_matrix.csv`
- `data/reports/target_coverage_audit_20260711/issue_register.csv`
- `data/reports/target_coverage_gap_triage_20260711/TRIAGE_SUMMARY.md`
- `data/reports/target_coverage_gap_triage_20260711/source_interval_unverified_triage.csv`
- `data/reports/target_coverage_gap_triage_20260711/row_count_mismatch_triage.csv`
- `data/reports/target_coverage_gap_triage_20260711/missing_db_registration_candidates.csv`
- `data/reports/target_coverage_gap_triage_20260711/quality_failed_readonly_triage.csv`
- `docs/tasks/TASK-2026-07-12-005-source-interval-provenance-repair-apply.md`
- `data/reports/source_interval_provenance_repair_apply_full_20260712/SOURCE_INTERVAL_PROVENANCE_REPAIR_APPLY.md`
- `data/reports/source_interval_provenance_repair_dry_run_after_full_20260712/SOURCE_INTERVAL_PROVENANCE_REPAIR_DRY_RUN.md`
- `data/reports/target_coverage_audit_20260712_after_source_interval_full/coverage_summary.md`
- `docs/tasks/TASK-2026-07-12-006-lpv-actual-contract-registration-dry-run.md`
- `data/reports/lpv_actual_contract_registration_dry_run_20260712/LPV_ACTUAL_CONTRACT_REGISTRATION_DRY_RUN.md`
- `data/reports/lpv_actual_contract_registration_dry_run_20260712/registration_reconcile_ledger.csv`
- `data/reports/target_coverage_audit_20260712_after_lpv_reconcile/coverage_summary.md`
- `docs/tasks/TASK-2026-07-12-007-residual-data-risk-closeout-dry-run.md`
- `data/reports/quality_failed_root_cause_audit_20260712/QUALITY_FAILED_ROOT_CAUSE_AUDIT.md`
- `data/reports/quality_failed_root_cause_audit_20260712/quality_failed_root_cause_ledger.csv`
- `data/reports/duplicate_path_version_reconcile_20260712/DUPLICATE_PATH_VERSION_RECONCILE.md`
- `data/reports/duplicate_path_version_reconcile_20260712/duplicate_path_version_ledger.csv`
- `data/reports/reference_metadata_gap_reconcile_20260712/REFERENCE_METADATA_GAP_RECONCILE.md`
- `data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_gap_ledger.csv`
- `data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_sync_commands.csv`
- `docs/tasks/TASK-2026-07-12-008-reference-metadata-gap-apply-plan.md`
- `data/reports/reference_metadata_gap_apply_plan_20260712/REFERENCE_METADATA_GAP_APPLY_PLAN.md`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_candidate_rows.csv`
- `data/reports/reference_metadata_gap_apply_plan_20260712/apply_batches.csv`
- `data/reports/target_coverage_audit_20260712_after_residual_closeout/coverage_summary.md`
- `data/reports/target_coverage_audit_20260712_after_residual_closeout/issue_register.csv`
- `data/reports/target_coverage_gap_triage_20260711/metadata_gap_triage.csv`
- `docs/tasks/TASK-2026-07-12-001-ad-ec-op-weekly-row-count-reconcile.md`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/ROW_COUNT_RECONCILE_SUMMARY.md`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260711/row_count_reconcile.csv`
- `docs/tasks/TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair.md`
- `data/reports/ad_ec_op_weekly_metadata_repair_20260712/METADATA_REPAIR_SUMMARY.md`
- `data/reports/ad_ec_op_weekly_metadata_repair_20260712/metadata_repair_candidates.csv`
- `data/reports/ad_ec_op_weekly_metadata_repair_20260712/metadata_repair_apply.csv`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/ROW_COUNT_RECONCILE_SUMMARY.md`
- `data/reports/ad_ec_op_weekly_row_count_reconcile_20260712_after_repair/row_count_reconcile.csv`
- `data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/coverage_summary.md`
- `data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/issue_register.csv`
- `docs/tasks/TASK-2026-07-12-003-residual-data-risk-disposition.md`
- `data/reports/residual_data_risk_disposition_20260712/RESIDUAL_DATA_RISK_DISPOSITION.md`
- `data/reports/residual_data_risk_disposition_20260712/residual_issue_summary.csv`
- `docs/tasks/TASK-2026-07-12-004-source-interval-provenance-repair-dry-run.md`
- `data/reports/source_interval_provenance_repair_dry_run_20260712/SOURCE_INTERVAL_PROVENANCE_REPAIR_DRY_RUN.md`
- `data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv`
- `data/reports/source_interval_provenance_repair_dry_run_20260712/affected_coverage_rows.csv`
