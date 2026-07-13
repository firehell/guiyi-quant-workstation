# DATA-FINAL-003-REV1：冻结验收口径修订与实际目标矩阵落地

| 字段 | 值 |
|---|---|
| 任务 ID | DATA-FINAL-003-REV1 |
| 风险 | R1 |
| 状态 | R1_DEV_COMPLETE_REVIEW_REQUIRED |
| 前置 | DATA-FINAL-002 DEV_COMPLETE |
| supersedes | DATA-FINAL-003 |
| audit_end | 2026-07-10 |
| 写入边界 | 不写 PostgreSQL；不写 Parquet；不调用 RQData；不启动 live/runtime/archive |

## 1. 修订结论

DATA-FINAL-003 原冻结口径不再作为最终验收依据。REV1 将冻结口径修订为实际目标矩阵驱动：

- `missing_expected` 只是过渡状态，不属于 DATA-1M-003 或 HIST-GATE-001 的最终可接受状态。
- `superseded` 不是 coverage 状态，只能作为 lineage 或 ignored evidence。
- 目标行只有存在有效 `primary`、`quality_status=passed`、physical passed、coverage passed 证据时，才能为 `covered_passed`。
- `approved_warning` 必须绑定正式 approval/evidence identifier；没有 approval 的 warning 只能是 `covered_warning`。
- actual dominant 的 1m 需求必须按消费者冻结，分钟回测、分钟策略、trigger price、实时预警和 archive 所需 actual 1m 不能笼统设为 optional。
- partial/confirmed/revision 以交易日历、正式收盘、archive 成功和 latest accepted revision 为准，不再机械排除 audit_end 所在周。

## 2. 正式状态语义

目标矩阵 `actual_status` 只允许以下 7 种值：

| 状态 | 定义 | 必填证据 |
|---|---|---|
| `covered_passed` | active primary + passed quality + physical passed + coverage passed | `evidence_id`、`data_version`、`quality_status=passed` |
| `covered_warning` | active primary 存在但质量或 lineage 仍为 warning/unchecked | `status_reason` |
| `approved_warning` | warning 已有正式批准或审计证据 | `evidence_id` |
| `not_applicable` | 目标不适用 | `na_reason` |
| `missing` | expected 目标无有效 active evidence | `recommended_next_task` |
| `missing_expected` | expected 目标处于过渡缺口 | `status_reason`、`recommended_next_task` |
| `failed` | 物理读取、行数、checksum、quality failed 或冲突失败 | `status_reason`、`recommended_next_task` |

`superseded` 不允许进入 `actual_status`。

## 3. R1 实现范围

已实现：

- `target_coverage_audit.py` 输出 REV1 矩阵字段：`product`、`contract_role`、`period`、`year`、`expected`、`expected_start`、`expected_end`、`actual_status`、`status_reason`、`evidence_id`、`data_version`、`quality_status`、`missing_count`、`na_reason`、`recommended_next_task`、`audit_end`。
- `target_coverage_audit.py` 增加 `validate_rev1_matrix()` 和 `build_rev1_exact_statistics()`。
- `target_coverage_audit.py` 增加 superseded 只读分类：`total_superseded_records`、`target_has_valid_primary`、`target_without_valid_primary`、`path_mismatch`、`checksum_mismatch`、`window_mismatch`、`duplicate_or_ambiguous`、`manual_review`。
- `data_layer_final_audit.py` 增加 `build_one_day_lineage_samples()`、`build_actual_consumer_matrix()`、`build_partial_revision_policy()`。
- `rqdata_data_layer_final_audit.py` 在 DB 不可用时输出 blocked active-gate snapshot，不编造 Stage8.6 结果。
- 标准结果包输出到 `.ai/results/DATA-FINAL-003-REV1/`。

未做：

- 不修改 DATA-FINAL-CHECKPOINT-1 为通过。
- 不开始 DATA-META-001。
- 不执行 `duplicate_active_supersede.py --confirm`。
- 不写 DB schema、constraint 或 active metadata。
- 不写或覆盖 Parquet，不调用 RQData。

## 4. Gate 状态

| Gate | 状态 | 说明 |
|---|---|---|
| 状态枚举只有 7 种 | PASS | 测试覆盖 `actual_status` 非空和非法状态阻断 |
| `missing_expected` 最终 Gate 阻断 | PASS | `validate_rev1_matrix(final_gate=True)` 阻断 |
| `superseded` 不作为 coverage 状态 | PASS | superseded 无有效 primary 时不能 `covered_passed` |
| `approved_warning` 必须有 evidence | PASS | 测试阻断无 evidence 的 approved warning |
| actual 1m consumer requirement | PASS | consumer matrix 明确 Backtest/Signal/trigger/live/archive 的 actual 1m required |
| partial/revision | PASS | 测试覆盖周五 archive success 可 confirmed、未完成周 partial、latest accepted revision |
| 2020-2022 1d lineage 样本 | PARTIAL/BLOCKED | 代码可生成样本；当前 DB registration 只读查询不可用时必须标记 blocked |
| 真实冻结目标矩阵 | PARTIAL/BLOCKED | 可生成 manifest-only 矩阵；DB registration 精确证据需只读 DB 或 API snapshot |

## 5. 验收与后续

R1 代码和测试完成后，仍不能直接进入 DATA-FINAL-CHECKPOINT-1。只有在只读 DB 或等价 API snapshot 可用、真实矩阵不含未解释 BLOCKED、1d lineage 样本完整可追踪后，REV1 才可从 `R1_DEV_COMPLETE_REVIEW_REQUIRED` 升级为 `FROZEN_ACCEPTANCE_SPEC`。
