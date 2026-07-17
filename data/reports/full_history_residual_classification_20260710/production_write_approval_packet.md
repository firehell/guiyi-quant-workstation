# Production Write Approval Packet — B2-04A

状态：`APPROVAL_REQUIRED / NO_WRITE_EXECUTED`

本文件只描述后续动作范围，不构成生产写入、RQData 调用、quality 修改或 binding 切换授权。

## 精确队列范围

| queue/action | action rows | code | manifest | DB | Parquet | RQData |
|---|---:|---:|---:|---:|---:|---:|
| `code_fix_queue` | 3 | 3 | 0 | 0 | 0 | 0 |
| `metadata_repair_queue` | 3979 | 0 | 1394 | 2579 | 0 | 0 |
| `local_data_rebuild_queue` | 252 | 0 | 252 | 252 | 252 | 0 |
| `rqdata_download_candidate_queue` | 479 | 0 | 479 | 479 | 479 | 479 |

## Metadata repair 明细

| action_type | action rows | scope |
|---|---:|---|
| `create_missing_registration_metadata` | 18 | existing physical files lacking complete metadata |
| `reconcile_db_registration` | 2471 | existing DB registration path identities |
| `regenerate_processed_summary` | 23 | processed summary JSON files |
| `repair_manifest_checksum` | 1377 | manifest path identities whose physical SHA-256 is verified |
| `repair_trading_calendar_boundary` | 90 | product trading-calendar boundaries |

## 已物化写集合

| write class | exact count | exact scope | approval state |
|---|---:|---|---|
| processed summary file replacement | 23 | queue 中列出的 JSON 路径 | 可单独审批 |
| existing manifest checksum row update | 1377 | 1377 个精确 `manifest.csv#line` | 可单独审批 |
| new manifest identity row | 17 | 现存 `p` 1m physical path | 可单独审批 |
| existing `market_data_files` row reconciliation | 2856 | 2471 个 path identity；精确 DB IDs 已写入 queue evidence | 可单独审批 |
| new `market_data_files` registration | 18 | 18 个现存 physical path | 可单独审批；quality-report 写入须另行物化 |
| trading-calendar repair planning scope | 90 | 90 个 product 到 `2026-07-10` | 尚不可批准生产写入：SQL row set 未物化 |
| local derived rebuild target | 252 | 63 products × 4 periods (`5m/15m/30m/60m`) | 尚不可批准生产写入：输出 partition/path 未物化 |
| RQData download candidate interval | 479 | 28 products；475 个 1d + 4 个 1m interval | 尚不可批准：必须在 code fix 重跑后重审 |

上表区分了 queue action 数与真实表/文件写入数。未物化出精确 SQL row set 或新 Parquet path 的类别明确保持 `APPROVAL_BLOCKED_WRITE_SET_NOT_MATERIALIZED`，不得把 90/252/479 个规划范围直接当成生产写入授权。

## 写入约束

- DB 写入前必须重新建立 direct PostgreSQL snapshot，并记录精确 row IDs。
- manifest/processed summary 写入前必须逐文件备份或用 Git 可恢复版本化变更。
- Parquet 必须新版本写入并原子切换；不得覆盖当前 canonical 文件。
- RQData 下载仅限候选 CSV 中 physical/manifest/DB 均不存在、且 provider/listing 边界已证明的行。
- quality 状态不得自动改写；warning 不得提升 passed。
- Profile binding 不得在这些队列中切换。

## 分批审批建议

1. `CODE_ONLY`：仅 code_fix_queue，重跑后重新生成所有后续队列。
2. `METADATA_ONLY`：processed summary/manifest/DB/calendar 分类型审批，不含 Parquet/RQData。
3. `LOCAL_REBUILD_ONLY`：仅 derived-from-1m，本地重建，不调用 RQData。
4. `RQDATA_DOWNLOAD_ONLY`：仅最终重审后仍存在的下载候选。

## 回滚

每条 queue row 自带 `rollback_method`。任何后续写任务必须在写前记录 Git commit、DB snapshot、manifest checksum 和新旧 Parquet version；失败时按 action row 精确回滚，不做目录级清理。
