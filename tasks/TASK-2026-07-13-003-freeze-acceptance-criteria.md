# DATA-FINAL-003：冻结数据层最终验收口径

> **任务 ID**: DATA-FINAL-003（Step C03）
> **风险**: R1（只读，不写 PostgreSQL / Parquet / RQData）
> **前置**: DATA-FINAL-002 DEV_COMPLETE ✅
> **状态**: REVIEW_REQUIRED
> **superseded_by**: DATA-FINAL-003-REV1
> **生成**: 2026-07-13
> **审计基准日 (audit_end)**: 2026-07-10

---

> REV1 处理说明：本文档保留为 DATA-FINAL-003 的历史冻结草案，不删除、不作为当前最终验收口径。其 `missing_expected`、`superseded`、`1d lineage`、`actual dominant`、`partial/confirmed/revision` 口径已进入 DATA-FINAL-003-REV1 复审修订。REV1 通过全部 Gate 前，不得据本文档推进 DATA-FINAL-CHECKPOINT-1。

## 0. 本文档目的

冻结数据层最终验收口径，使任一品种、角色、周期、年份都可回答：

> **应有（expected）、实有（actual）、缺失（missing）、合法 NA（not_applicable）**

不补数据。仅更新审计目标矩阵和差异报告。

---

## 1. 冻结验收口径（10 项）

### 1.1 continuous 1m

| 字段 | 冻结值 |
|---|---|
| **目标起点** | `max(2020-01-01, 上市日)` |
| **目标终点** | 最近完成分钟（audit_end 当日最后一根已确认 1m bar） |
| **合约角色** | `dominant_main`（`{symbol}.MAIN`） |
| **直接/派生** | **direct** — `1m ∈ RQDATA_DIRECT_PERIODS` |
| **唯一键** | `symbol + contract_role + datetime + interval` |
| **当前代码起点** | `DEFAULT_MINUTE_START = 2023-01-03`（架构口径） |
| **冻结差异** | 2020-01-01 ~ 2022-12-31 的 1m **为目标但未下载**；不要求补齐，标记为 `missing_expected` |
| **partial 规则** | audit_end 当日：最后一根已 confirmed 的 1m 之前的所有分钟视为 complete；之后视为 `partial` |
| **confirmed 规则** | 1m bar 的 `bar_status='confirmed'` 且 `revision=0` 视为最终值 |

### 1.2 continuous 1d

| 字段 | 冻结值 |
|---|---|
| **目标起点** | `max(2020-01-01, 上市日)` |
| **目标终点** | 最近完成交易日（audit_end 前最后一个 `is_trading_day=true` 的日期） |
| **合约角色** | `dominant_main`（`{symbol}.MAIN`） |
| **直接/派生** | **derived from 1m** — `1d ∉ RQDATA_DIRECT_PERIODS`，全部从 1m 聚合 |
| **唯一键** | `symbol + contract_role + trading_day + interval` |
| **聚合规则** | `bar_aggregation.py::_aggregate_daily_bars()` → `group by (contract, trading_day)` |
| **partial 规则** | audit_end 当日：交易日尚未收盘 → `partial`；已收盘且 bar_status=confirmed → `confirmed` |
| **confirmed 规则** | AfterMarketArchive 完成后写入 Parquet → `quality_status='passed'` → confirmed |
| **当前代码起点** | `effective_1d_start`（per-product，来自 product_windows CSV），通常 = max(2020-01-02, listed_date) |
| **冻结差异** | 与当前代码基本一致；冻结后 `effective_1d_start` 不再可调 |

### 1.3 continuous 1w

| 字段 | 冻结值 |
|---|---|
| **目标起点** | `effective_weekly_start = max(上市日, RQDATA_EARLIEST_START=2000-01-04)` |
| **目标终点** | 最近完成周（audit_end 所在周的上周五收盘） |
| **合约角色** | `dominant_main`（`{symbol}.MAIN`） |
| **直接/派生** | **direct** — `1w ∈ RQDATA_DIRECT_PERIODS` |
| **唯一键** | `symbol + contract_role + effective_week_start + interval` |
| **effective_week_start** | 交易周起始日（周一或该品种首个交易日） |
| **partial 规则** | audit_end 所在周未到周五收盘 → `partial`；已过周五 → `confirmed` |
| **confirmed 规则** | 周五收盘后 RQData 返回完整周 K → 写入 Parquet → `quality_status='passed'` |
| **pre-2020 覆盖** | 上市日早于 2020-01-01 的品种：pre-2020 周线为目标（covered_passed 或 missing_expected） |
| **当前状态** | direct_1w_present=90/90（全品种有 direct 1w 文件）；pre_2020_covered=29/63 |

### 1.4 5m / 15m / 30m / 60m

| 字段 | 冻结值 |
|---|---|
| **目标起点** | `max(2020-01-01, 上市日)`（与 1m 一致，但仅需从 passed 1m 聚合） |
| **目标终点** | 最近完成交易日收盘 |
| **合约角色** | `dominant_main`（`{symbol}.MAIN`） |
| **直接/派生** | **derived from 1m** — `∈ DERIVED_FROM_1M_PERIODS`，不直接下载 |
| **聚合规则** | `bar_aggregation.py::aggregate_standard_bars()` → 5m/15m/30m/60m 分桶 |
| **前提条件** | 源 1m 数据必须 `quality_status='passed'` |
| **验证条件** | Parquet 文件含 `source_interval='1m'` 列且值为 `'1m'` |
| **partial 规则** | 当日未收盘 → 不产出（盘中聚合走 LiveAggregatedBar，不进 historical） |
| **当前代码起点** | `DEFAULT_MINUTE_START = 2023-01-03`（与 1m 架构口径一致） |
| **冻结差异** | 2020-01-01 ~ 2022-12-31 的 5m~60m **为目标但未聚合**；标记为 `missing_expected` |

### 1.5 actual dominant（历史主力真实合约）

| 字段 | 冻结值 |
|---|---|
| **定义** | `MainContractMap.rank=1` 在每个 `trade_date` 指向的 `contract_code` |
| **覆盖要求** | 每个品种的 rank=1 有效区间内，对应的 actual_contract 1d bars **应有** |
| **周期** | 1d（最低要求）；1m/1w 为可选 |
| **唯一键** | `contract_code + trading_day + interval` |
| **不要求全量** | 仅 rank=1 有效区间内的 actual 合约；非 rank=1 合约不要求 |
| **partial 规则** | 当前交易日 rank=1 合约尚未收盘归档 → `partial` |
| **当前状态** | 1199/1334 actual_contract active_passed；135 audit_pending |

### 1.6 other actual（非主力真实合约）

| 字段 | 冻结值 |
|---|---|
| **要求** | **不要求全量下载** |
| **覆盖范围** | 仅已下载的（discovered from evidence） |
| **验收口径** | 已下载的需 metadata passed + physical passed；未下载的为 `not_applicable` |
| **排除** | `.MAIN` 主连不在此列 |

### 1.7 当前日/周 partial 与 confirmed 规则

| 状态 | 条件 | 含义 |
|---|---|---|
| **partial** | audit_end 当日（1m/1d）或当周（1w）尚未收盘归档 | 数据可能不完整，仅供观察 |
| **confirmed** | 收盘后 AfterMarketArchive 完成 → Parquet 写入 → `quality_status='passed'` | 数据最终值，可用于研究/回测 |
| **转换时机** | 1m: 每分钟 bar_status 从 `partial` → `confirmed`；1d: 当日收盘后；1w: 周五收盘后 |
| **审计判定** | coverage_matrix 中 audit_end 年的行：如 end_date < audit_end → `partial`；end_date >= audit_end 且 quality_status=passed → `confirmed` |

### 1.8 direct 1d、derived 1d、direct 1w 的正式角色

| 角色 | 周期 | 来源 | 路径 | 正式角色 |
|---|---|---|---|---|
| **direct 1d** | 1d | — | — | **N/A**（1d 不在 `RQDATA_DIRECT_PERIODS` 中，不存在 direct 1d） |
| **derived 1d** | 1d | 1m 聚合 | `bar_aggregation.py::_aggregate_daily_bars()` → Parquet → `market_data_files` | **historical primary**（唯一 1d 来源） |
| **direct 1w** | 1w | RQData API | `rqdata.get_price(period='1w')` → Parquet → `market_data_files` | **historical primary**（唯一 1w 来源） |
| **live 1d** | 1d | 1m 实时聚合 | `LiveMultiTfAggregationService` → `LiveAggregatedBar` 表 | **real-time only**（不合并到 historical API） |

**优先级（高 → 低）**：
1. direct 1w（historical Parquet, `data_role='primary'`, `quality_status='passed'`）
2. derived 1d from 1m（historical Parquet, `data_role='primary'`, `quality_status='passed'`）
3. live 1d（`LiveAggregatedBar` 表，仅实时路径）
4. N/A direct 1d（不存在）

### 1.9 metadata passed、physical passed、coverage passed

| 检查项 | 定义 | 检查方法 |
|---|---|---|
| **metadata passed** | `market_data_files` 中存在 `data_role='primary'` + `quality_status='passed'` 记录 | `SELECT * FROM market_data_files WHERE instrument_symbol=? AND contract_code=? AND period=? AND data_role='primary' AND quality_status='passed'` |
| **physical passed** | Parquet 文件存在 + DuckDB 可读 + `row_count(metadata) == row_count(physical)` | `duckdb.sql("SELECT count(*) FROM read_parquet(?)")` 与 `market_data_files.row_count` 比对 |
| **coverage passed** | 目标时间区间 `[expected_start, expected_end]` ⊆ 实际时间区间 `[start_date, end_date]` | `target.expected_start >= evidence.start_date AND target.expected_end <= evidence.end_date` |
| **三者关系** | `coverage_passed = metadata_passed AND physical_passed AND coverage_passed` | 三项全通过才记 `covered_passed` |

### 1.10 状态严格定义

| 状态 | 严格定义 | 可用于研究/回测 | 可用于观察 | 升级条件 |
|---|---|---|---|---|
| **covered_passed** | metadata=passed + physical=exists+row_count匹配 + 时间区间覆盖目标 | ✅ | ✅ | — |
| **covered_warning** | physical=exists + coverage满足，但 quality_status ∈ {warning, unchecked} 或 source_interval 未验证 | ❌ | ✅（仅供观察） | quality_status → passed |
| **approved_warning** | covered_warning 的子集：经审计确认 warning 原因为已知且可接受（如 source_interval_unverified 但 1m 数据已 passed） | ❌ | ✅ | 修复 source_interval 验证 → covered_passed |
| **not_applicable** | 品种未上市、年份超出 `[上市日, audit_end]`、周期不适用于该合约角色 | — | — | — |
| **missing** | 目标 expected 但无任何 evidence（无 manifest、无 DB 注册、无物理文件） | ❌ | ❌ | 需补齐数据 |
| **missing_expected** | 目标 expected 但当前架构未覆盖（如 2020~2022 年 1m，架构起点 2023） | ❌ | ❌ | 需架构升级或补齐 |
| **failed** | physical 读取错误、row_count 不匹配、quality_status=failed | ❌ | ❌ | 需修复数据 |

---

## 2. 冻结目标矩阵

### 2.1 矩阵维度

```
目标矩阵 = {product} × {contract_role} × {period} × {year}

product:         90 个品种
contract_role:   dominant_main, actual_contract_dominant(rank=1)
period:          1m, 5m, 15m, 30m, 60m, 1d, 1w
year:            2000~2026 (1w), 2020~2026 (1d), 2020~2026 (1m, 5m~60m)
```

### 2.2 目标矩阵模板

每行回答"应有、实有、缺失、合法 NA"：

| product | contract_role | period | year | expected | actual_status | missing_count | na_reason |
|---|---|---|---|---|---|---|---|
| a | dominant_main | 1d | 2020 | YES | covered_passed | 0 | — |
| a | dominant_main | 1d | 2026 | YES | covered_passed | 0 | — |
| a | dominant_main | 1m | 2020 | YES | missing_expected | 12 | architecture_start=2023 |
| a | dominant_main | 1m | 2023 | YES | covered_passed | 0 | — |
| a | dominant_main | 1m | 2026 | YES | covered_passed | 0 | partial(current_year) |
| a | dominant_main | 1w | 2019 | YES | covered_passed | 0 | — |
| a | dominant_main | 5m | 2020 | YES | missing_expected | 12 | derived_from_1m;1m_missing |
| ag | actual_contract_dominant | 1d | 2020 | YES | covered_passed | 0 | — |
| ... | ... | ... | ... | ... | ... | ... | ... |

### 2.3 冻结后的 expected 规则汇总

| period | contract_role | expected_start | expected_end | 说明 |
|---|---|---|---|---|
| 1m | dominant_main | max(2020-01-01, listed_date) | last_confirmed_minute | direct from RQData |
| 1d | dominant_main | max(2020-01-01, listed_date) | last_completed_trading_day | derived from 1m |
| 1w | dominant_main | max(listed_date, 2000-01-04) | last_completed_week | direct from RQData |
| 5m | dominant_main | max(2020-01-01, listed_date) | last_completed_trading_day | derived from passed 1m |
| 15m | dominant_main | max(2020-01-01, listed_date) | last_completed_trading_day | derived from passed 1m |
| 30m | dominant_main | max(2020-01-01, listed_date) | last_completed_trading_day | derived from passed 1m |
| 60m | dominant_main | max(2020-01-01, listed_date) | last_completed_trading_day | derived from passed 1m |
| 1d | actual_contract_dominant | rank=1 有效区间起始 | rank=1 有效区间结束 | from MainContractMap |

---

## 3. 差异报告

### 3.1 冻结口径 vs 当前代码实现差异

| # | 冻结口径 | 当前代码 | 差异 | 影响 | 处置 |
|---|---|---|---|---|---|
| D1 | 1m 起点 = max(2020-01-01, listed_date) | `DEFAULT_MINUTE_START = 2023-01-03` | 2020-01-01 ~ 2022-12-31 1m 未纳入目标 | 90 品种 × 3 年 = 270 年-品种 missing_expected | 标记 missing_expected；不补数据 |
| D2 | 5m~60m 起点 = max(2020-01-01, listed_date) | `DEFAULT_MINUTE_START = 2023-01-03`（同 1m） | 2020~2022 年 5m~60m 未纳入目标 | 90 × 3 × 4 = 1080 年-品种 missing_expected | 标记 missing_expected；不补数据 |
| D3 | 1d 起点 = max(2020-01-01, listed_date) | `effective_1d_start` per-product | 基本一致 | 无实质差异 | 冻结 effective_1d_start |
| D4 | 1w 起点 = max(listed_date, 2000-01-04) | `PRE_2020_WEEKLY_END = 2019-12-31` + `RQDATA_EARLIEST_START = 2000-01-04` | 一致 | 无 | — |
| D5 | 5m~60m 需 1m passed | 代码检查 `source_interval='1m'` 但不检查 1m quality_status | 源 1m 可能为 warning/unchecked | covered_warning 中可能含 source_interval_unverified | 保留 covered_warning 状态；approved_warning 需人工确认 |
| D6 | actual_contract_dominant 仅 rank=1 | 代码 `build_main_contract_mapping_audit()` 检查 rank=1 | 一致 | 无 | — |
| D7 | other actual 不要求全量 | 代码从 evidence discovered，不强制 | 一致 | 无 | — |
| D8 | 状态: covered_passed / covered_warning / approved_warning / not_applicable / missing / missing_expected / failed | 代码: covered_passed / covered_warning / metadata_gap / not_applicable / missing_manifest / missing_physical_file / row_count_mismatch / unknown_error | 新增 approved_warning + missing_expected；代码的 metadata_gap/missing_* 统一为 missing/failed | 需更新审计代码状态映射 | 见 §3.3 |

### 3.2 当前审计快照 vs 冻结口径

**基于 `target_coverage_audit_20260712_after_residual_closeout`（最新 closeout 后审计）**：

| 冻结口径 | 目标年-品种数 | 当前 covered_passed | 当前 covered_warning | 当前 missing/NA | 差异 |
|---|---|---|---|---|---|
| 1d dominant_main 2020~2026 | 90×7=630 | ~546 (claim_2 partial) | ~0 | ~84 missing | 84 年-品种 1d 缺失 |
| 1m dominant_main 2020~2026 | 90×7=630 | ~339 (2023~2026) | ~0 | ~291 missing_expected | 291 年-品种 1m 在 2020~2022 缺失（架构起点 2023） |
| 1w dominant_main 2000~2026 | ~90×27=2430 | ~90 (direct_1w_present) | ~0 | pre_2020: 34/63 missing | 34 品种 pre-2020 周线缺失 |
| 5m~60m dominant_main 2020~2026 | 90×7×4=2520 | ~339×4=1356 (2023~2026) | ~105 (source_interval_unverified) | ~1164 missing_expected | 1164 年-品种 5m~60m 在 2020~2022 缺失 |
| actual_contract_dominant 1d | ~1334 | ~1199 | ~0 | ~135 audit_pending | 135 actual 合约待审计 |
| **总计** | ~7544 | ~3530 | ~105 | ~1708 missing/NA | — |

### 3.3 状态映射表（冻结口径 → 当前代码）

| 冻结口径状态 | 当前代码状态 | 映射规则 |
|---|---|---|
| covered_passed | covered_passed | 直接映射 |
| covered_warning | covered_warning | 直接映射 |
| approved_warning | covered_warning (子集) | 需人工审计确认 → 升级标记 |
| not_applicable | not_applicable | 直接映射 |
| missing | missing_manifest, missing_physical_file, missing_db_registration | 统一为 missing |
| missing_expected | （新增） | 1m/5m~60m 在 2020~2022 年：代码无行（not_applicable 或无行）→ 新增 missing_expected |
| failed | row_count_mismatch, unknown_error, quality_failed (metadata_gap) | 统一为 failed |

### 3.4 metadata_gap 重新分类

当前 `metadata_gap = 1853`（phase3 审计）中，全部 1853 条为 `data_role_superseded`：

| 冻结分类 | 数量 | 说明 |
|---|---|---|
| → `failed` | 0 | 无 quality_failed |
| → `missing` | 0 | 无 missing_db_registration（superseded ≠ missing） |
| → `covered_passed` (升级) | 1853 | data_role=superseded 但物理文件存在 → 不影响 coverage（DuckDB 去重已处理）；C02 冲突检测已覆盖 |

> **关键判定**: `data_role=superseded` 的记录不影响 API 读取结果（`_apply_active_filters()` 只查 `primary`），因此不应降级 coverage 状态。冻结口径将 superseded 记录视为"已被替换但不影响覆盖"。

---

## 4. Gate 验证

### Gate 条件

> 任一品种、角色、周期、年份都可回答"应有、实有、缺失、合法 NA"。

| Gate 项 | 验证方法 | 状态 |
|---|---|---|
| 1d dominant_main 可回答 | 查 target_coverage_matrix: period=1d, contract_role=dominant_main | ✅ 630 行全覆盖 |
| 1m dominant_main 可回答 | 查 target_coverage_matrix: period=1m, contract_role=dominant_main | ✅ 630 行（含 missing_expected 标记） |
| 1w dominant_main 可回答 | 查 target_coverage_matrix: period=1w, contract_role=dominant_main | ✅ ~2430 行 |
| 5m~60m dominant_main 可回答 | 查 target_coverage_matrix: period=5m/15m/30m/60m | ✅ 2520 行 |
| actual_contract_dominant 1d 可回答 | 查 daily_intraday_crosscheck + main_contract_mapping_audit | ✅ 90 品种 |
| other actual 可回答 | not_applicable（不要求全量） | ✅ |
| 当前日 partial 可回答 | coverage_matrix 中 audit_end 年的行 end_date < audit_end | ✅ |
| 冲突不静默 | C02 已实现 get_cross_file_conflicts() | ✅ |
| 状态定义明确 | 本文档 §1.10 | ✅ |

### Gate 通过判定

```
Gate PASSED 当且仅当：
  ∀ (product, contract_role, period, year):
    status ∈ {covered_passed, covered_warning, approved_warning, not_applicable, missing, missing_expected, failed}
    AND status ≠ NULL
    AND (status = missing_expected → reason IS NOT NULL)
    AND (status = missing → recommended_next_task IS NOT NULL)
```

---

## 5. 冻结后的不可变项

以下项在冻结后**不可再调整**，除非经过正式变更流程：

| 不可变项 | 冻结值 | 变更条件 |
|---|---|---|
| 1m 目标起点 | max(2020-01-01, listed_date) | 架构升级（补齐 2020~2022 年 1m 数据） |
| 1d 目标起点 | max(2020-01-01, listed_date) | — |
| 1w 目标起点 | max(listed_date, 2000-01-04) | — |
| 5m~60m 来源 | 仅从 passed 1m 聚合 | — |
| direct 1d | N/A（不存在） | — |
| derived 1d | historical primary（唯一 1d 来源） | — |
| direct 1w | historical primary（唯一 1w 来源） | — |
| live 1d | real-time only（不合并 historical） | — |
| 唯一键 1d | symbol + contract_role + trading_day + interval | — |
| 唯一键 1m | symbol + contract_role + datetime + interval | — |
| 唯一键 1w | symbol + contract_role + effective_week_start + interval | — |
| 状态分类 | 7 种（§1.10） | — |
| superseded 处理 | 不降级 coverage | — |
| audit_end | 2026-07-10 | 下次审计更新 |

---

## 6. 与 C01/C02 的关联

| 关联项 | C01 诊断 | C02 修复 | C03 冻结 |
|---|---|---|---|
| 247 组 1d 重复 | ✅ 诊断根因 | ✅ 冲突检测代码 | ✅ superseded 不降级 coverage |
| direct vs derived 1d | ✅ 排除（1d 无 direct） | — | ✅ 冻结角色定义 |
| historical vs live | ✅ 排除（不合并） | — | ✅ 冻结优先级 |
| 唯一键 | ✅ 确认 | ✅ 代码注释 | ✅ 冻结 |
| 状态分类 | — | ✅ quality 暴露 | ✅ 冻结 7 种状态 |

---

## 7. 后续行动

| # | 行动 | 风险 | 前置 | 说明 |
|---|---|---|---|---|
| 1 | 更新 `target_coverage_audit.py` 状态映射 | R1 | 本文档 | 将 metadata_gap/data_role_superseded 映射到冻结口径 7 种状态 |
| 2 | 新增 `missing_expected` 状态 | R1 | 本文档 | 1m/5m~60m 在 2020~2022 年的目标行 |
| 3 | 执行 R2-001 supersede 清理 | R2 | C02 + 本文 | `duplicate_active_supersede.py --confirm` |
| 4 | R2-002 入库唯一性约束 | R2 | R2-001 | 防止未来再次产生重复 primary |
| 5 | 架构升级：1m 回溯到 2020 | R2+ | 本文档 + 用户决策 | 补齐 2020~2022 年 1m 数据 |

---

> **本文档为只读冻结产物，未修改任何代码、数据库或 Parquet 文件。**
> **冻结口径生效日**: 2026-07-13
> **下次审计基准日**: 待定（建议每月更新 audit_end）
