# FULL-HISTORY-RESIDUAL-CLASSIFICATION-004A

状态：`RESIDUALS_CLASSIFIED`

本报告只读分类 B2-03 的全部 residual。未修改代码、DB、Parquet、manifest、quality 或 binding，未调用 RQData。

## 输入与边界

- 审计终点：`2026-07-10`
- B2-03 residual 行数：`7263`
- direct PostgreSQL 证据来自 B2-03 full inventory snapshot；本任务未连接或写入 DB。
- 分类优先使用 physical SHA-256、全部 manifest 聚合、processed summary 与 direct DB 的交叉证据。

## 分类计数

| classification | rows |
|---|---:|
| `audit_model_error` | 483 |
| `manifest_aggregation_error` | 0 |
| `path_normalization_error` | 0 |
| `processed_summary_stale` | 44 |
| `db_registration_stale` | 2478 |
| `db_registration_missing` | 52 |
| `duplicate_same_path` | 0 |
| `duplicate_same_content` | 140 |
| `duplicate_conflicting_content` | 0 |
| `quality_warning_accepted` | 71 |
| `quality_failed` | 0 |
| `checksum_mismatch` | 1379 |
| `physical_missing` | 731 |
| `reference_metadata_not_applicable` | 360 |
| `reference_metadata_missing` | 180 |
| `profile_rule_block` | 1345 |
| `manual_review` | 0 |

## 执行队列

| queue | rows | 含义 |
|---|---:|---|
| `code_fix_queue.csv` | 3 | 先修 Audit V2 边界、重复输出和 session 适用性模型 |
| `metadata_repair_queue.csv` | 3979 | processed summary、manifest checksum、DB registration、calendar 的候选修复 |
| `local_data_rebuild_queue.csv` | 252 | 仅由 canonical 1m 本地派生，不需要 RQData |
| `rqdata_download_candidate_queue.csv` | 479 | physical + manifest + DB 全部缺失且位于支持边界内 |

## 关键结论

- B2-03 的 actual-roll 缺口中，`483` 行属于边界模型错误，必须先修代码再重跑。
- `18` 个 `p` 1m 路径需要 metadata 修复：17 个缺 manifest/DB，1 个已有 manifest 但缺 DB；均不进入下载队列。
- `23` 个 processed summary 文件把 direct DB `warning` 表述为 `failed`；不允许借此修改 quality。
- `90` 个 trading-session residual 不应按静态年度配置机械补行，归类为 not applicable/model fix。
- 真正满足下载候选四重证明的唯一队列为 `479` 行；本任务未下载。
- `quality_warning_accepted` 仍是 warning，不提升为 passed；passed-only Profile 继续阻断。

## 推荐顺序

1. 先执行 code fix 并重跑 Audit V2，消除边界和重复输出误报。
2. 再审批 metadata repair；每类写入必须使用 approval packet 的精确范围。
3. 本地 derived rebuild 与 RQData 下载分别独立审批，禁止合并为一次大写入。
4. 所有写入后重新运行 full checksum、DuckDB、direct DB 与 Profile eligibility Gate。

## 输出

- `residual_classification.csv`：每条输入 residual 的完整分类与写入标志。
- 四个 queue CSV：按实际动作去重后的执行候选。
- `production_write_approval_packet.md`：精确写入范围；不是授权。
