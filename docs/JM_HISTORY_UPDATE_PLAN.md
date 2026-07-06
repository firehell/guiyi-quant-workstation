# JM History Update Plan

生成时间：2026-07-06
阶段：Stage 2-B，JM 历史数据更新只读计划验证
性质：readonly RQData plan verification / docs update

## 1. 结论摘要

本轮完成 JM 历史数据更新到最新交易日前的执行设计，暂不进入真实写入。

- 阶段 1 RQData 权限与接口能力 PoC 结论为 `PARTIAL`，但历史 bar 更新所需核心能力可作为阶段 2 设计依据。
- 已确认可用能力包括 RQData import/auth、JM 合约目录、DCE JM 合约列表、1d/1m 小样本、5m/15m/30m/60m 直取、主力映射、合约乘数、保证金和手续费字段。
- 仍需后续确认 `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本原因，以及 realtime wrapper。
- 本轮没有运行真实 RQData。
- 本轮没有写 `data/`。
- 本轮没有写数据库。
- 本轮没有写 parquet、manifest、checksum 或 quality report。
- 本轮没有修改后端、前端、策略、回测或 migration。

Stage 2-B 已运行受控只读 plan verification，确认实际最新交易日和主力合约段；但当前脚本只覆盖 `1m/5m/15m/1d`，没有覆盖目标要求中的 `30m/60m`，因此不得进入 Stage 2-C 写入。

本轮没有写 `data/`，没有写数据库，没有写 parquet、manifest、checksum 或 quality report，没有修改业务代码，也没有运行任何 sync / asset / ingest 写入脚本。

## 2. 当前数据资产状态

当前正式研究数据窗口仍停在 `2025-12-31`。阶段 1 PoC 不代表 JM 历史数据已经执行增量更新。

| timeframe | current_start | current_end | current_rows | current_data_version | update_needed |
|---|---|---|---:|---|---|
| 1d | 2023-01-03 | 2025-12-31 | 727 | `rqdata_jm_standard_1d_20230103_20251231_v1` | yes |
| 1m | 2023-01-03 | 2025-12-31 | 248535 | `rqdata_jm_standard_1m_20230103_20251231_v1` | yes |
| 5m | 2023-01-03 | 2025-12-31 | 49707 | `rqdata_jm_standard_5m_20230103_20251231_v1` | yes |
| 15m | 2023-01-03 | 2025-12-31 | 16569 | `rqdata_jm_standard_15m_20230103_20251231_v1` | yes |
| 30m | unknown | unknown | unknown | unknown | yes, method TBD |
| 60m | unknown | unknown | unknown | unknown | yes, method TBD |

待确认项：

- `30m` / `60m` 是否已有已登记 standard asset；当前任务不读取数据库确认。
- `30m` / `60m` 优先使用 RQData 直取，还是以 `1m` 聚合作为主路径。
- 如果使用 `1m` 聚合，需要先确认夜盘归属、交易日边界和未完成 K线过滤规则。

## 3. 目标数据范围设计

目标范围：

```text
start_exclusive = 2025-12-31
end_inclusive = RQData latest available trading day
```

执行原则：

- Stage 2-B 使用只读 plan verification 确认 `latest_available_trading_day`。
- 优先通过 RQData trading calendar / trading dates 获得更新日期序列。
- 如果 `trading_sessions` 继续返回 0 行，历史 bar 更新不依赖它完成；交易时段只用于后续聚合和质量审计增强，不作为 Stage 2-C 写入前置 blocker。
- `1m/5m/15m/30m/60m/1d` 均纳入目标周期。
- RQData 直取 `5m/15m/30m/60m` 已在 PoC 中通过接口形态验证，可作为 Stage 2-B 候选路径。
- `1m` 聚合多周期可作为校验或替代路径，但不能在未确认夜盘和交易日边界时替代正式质量结论。
- `continuous_contracts` 返回 0 行时，不依赖 continuous contract 接口作为合约切换依据；优先使用 dominant mapping 和实际合约段。

## 4. 输出路径设计

本节只设计路径，不执行写入。实际路径以 Stage 2-B 对现有脚本和目录约定的只读确认结果为准。

| asset | proposed_path | write_phase | notes |
|---|---|---|---|
| raw parquet | `data/raw/rqdata/dominant_contract_bars/product=jm/frequency=<timeframe>/year=<yyyy>/...` | Stage 2-C | 按现有 raw RQData 目录约定扩展；不得覆盖旧文件。 |
| standard parquet | `data/parquet/canonical/bars/provider=rqdata/period=<timeframe>/exchange=DCE/symbol=jm/contract=jm.MAIN/...` | Stage 2-C | 现有 `rqdata_v1b_jm_asset.py` 使用该 canonical 约定；本轮仅沿用为设计候选。 |
| manifest | `data/manifests/rqdata/jm/history_update_<latest>.csv` 或现有 manifest 目录 | Stage 2-D | 需由 Stage 2-B 确认现有 manifest helper 的实际路径。 |
| checksum | `market_data_files.checksum` plus manifest checksum field | Stage 2-D | 使用已有 `sha256_file` 口径；不自造第二套算法。 |
| quality report file | `data/processed/v1b/jm/jm_history_quality_<latest>.json` 或现有报告目录 | Stage 2-D | 文件路径需与 DB 登记一致。 |
| `market_data_files` | PostgreSQL `market_data_files` | Stage 2-D | 只登记 `provider=rqdata`、`data_role=primary` 且质量非 failed 的正式文件。 |
| `data_quality_reports` | PostgreSQL `data_quality_reports` | Stage 2-D | 与 `market_data_files.file_id` 关联，记录 check details。 |
| coverage audit report | `data/processed/v1b/jm/jm_history_coverage_audit_<latest>.json` 或 docs/report 输出 | Stage 2-E | 用于核对新旧版本覆盖、缺口、重复和 row count。 |

路径不明确处不新建体系；Stage 2-B 需要先核对现有 `bar_sample.py`、`manifest.py`、`parquet.py`、`rqdata_v1b_jm_asset.py` 的实际约定。

## 5. data_version 命名设计

目标新版本命名：

```text
rqdata_jm_standard_1m_20230103_<latest>_v2
rqdata_jm_standard_5m_20230103_<latest>_v2
rqdata_jm_standard_15m_20230103_<latest>_v2
rqdata_jm_standard_30m_20230103_<latest>_v2
rqdata_jm_standard_60m_20230103_<latest>_v2
rqdata_jm_standard_1d_20230103_<latest>_v2
```

规则：

- 不覆盖旧 `v1` 文件。
- 保留旧 `2025-12-31` 版本作为 rollback fallback。
- manifest 需要记录新旧版本关系、生成时间、输入范围、输出路径、row count、checksum、quality status。
- DB 登记需要保留旧记录，不硬删；如需切换 active 指针，使用 `data_role` / quality 状态或后续 manifest active marker 表达。
- 如果 Stage 2-B 发现现有代码仍生成 `rqdata_v1b_jm_*_v1`，Stage 2-C 前必须先调整或增加明确参数，不能把旧命名继续作为最新正式版本。

## 6. 质量检查设计

| check_id | check_name | applies_to | pass_condition | failure_action |
|---|---|---|---|---|
| Q001 | schema 检查 | all timeframes | 必备字段存在：`datetime/open/high/low/close/volume/open_interest/trading_day/source/provider/data_role/quality_status/data_version` | 标记 failed，阻止 active |
| Q002 | OHLC 合法性 | all timeframes | `high >= max(open, close, low)` 且 `low <= min(open, close, high)` | 标记 failed，输出样本 |
| Q003 | datetime 单调递增 | all timeframes | 排序后单调递增 | 标记 failed 或 warning，需人工审查 |
| Q004 | 重复 bar 检查 | all timeframes | 同一 `datetime` 无重复 | 标记 warning/failed，视重复数量阻止 active |
| Q005 | 缺口检查 | all timeframes | 与交易日期和周期预期相符，缺口可解释 | 标记 warning，缺口异常时阻止 active |
| Q006 | volume / turnover 非负 | all timeframes | `volume >= 0`，`turnover >= 0` 或字段缺省有明确处理 | 标记 failed |
| Q007 | open_interest 存在性 | all timeframes | 字段存在，负值数量为 0 | 标记 failed |
| Q008 | trading_day 检查 | all timeframes | 字段存在，夜盘归属规则明确 | 标记 warning/failed，进入人工审查 |
| Q009 | 时间范围 min/max | all timeframes | min/max 覆盖预期范围且不越界 | 标记 failed |
| Q010 | row count 预期范围 | all timeframes | 行数与交易日、周期、合约段大体一致 | 标记 warning，异常时阻止 active |
| Q011 | checksum 检查 | output files | 写入后 checksum 可复算且与 manifest / DB 一致 | 标记 failed，废弃新版本 |
| Q012 | source 检查 | standard parquet / DB | `source = rqdata` 或读取层映射为 `local_parquet` | 非法来源不得 active |
| Q013 | data_role 检查 | standard parquet / DB | `data_role = primary` 才可进入正式 active 链路 | 非 primary 不进入正式研究 |
| Q014 | quality_status 判定 | standard parquet / DB | 正式链路至少 `quality_status != failed`，严格研究优先 passed | failed 阻止 active |
| Q015 | DuckDB 可读性 | standard parquet | DuckDB 可读取 row count、min/max datetime | 标记 failed |

## 7. active 数据源收敛 Gate

正式 active 入口必须满足：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先：

```text
quality_status = "passed"
```

边界：

- validation 数据不能进入正式回测。
- legacy_reference 数据不能进入正式回测。
- candidate 数据不能进入正式回测。
- Web 如展示非 active 数据，必须明确标记其研究/历史/候选属性。
- signal scanner 不允许读取 legacy / validation / candidate 数据。
- failed 数据不得进入正式研究链路、回测入口、默认 Market API 或信号输入。

## 8. 回滚策略

- 新版本写入不覆盖旧 parquet。
- 新版本写入失败时，将新版本标记为 failed / abandoned，不删除旧版本。
- manifest 需要记录 `created`、`quality_checked`、`failed`、`superseded`、`active_candidate` 等状态；具体枚举由 Stage 2-D 按现有 helper 收敛。
- DB 登记失败时不应把 parquet 直接视为 active；需要生成失败记录或人工恢复说明。
- quality report 为 failed 时，`market_data_files.quality_status` 必须阻止 active。
- 旧 `2025-12-31` 数据版本保留为 rollback fallback。
- 不硬删旧 `market_data_files` / `data_quality_reports`；只允许状态标记或 data_role 调整。
- 不删除 handoff 包、旧报告、旧 parquet 或旧 manifest。

## 9. 后续任务拆分

| task_id | title | goal | allowed_scope | forbidden_scope | writes_data | writes_db | needs_rqdata | needs_plan | tests | acceptance |
|---|---|---|---|---|---|---|---|---|---|---|
| JM-UPDATE-2B-PLAN-VERIFY | JM update dry-run / plan verification | 确认最新交易日、合约段、周期清单和路径 | 只读脚本、文档、任务记录 | 不写 `data/`、DB、parquet、manifest | no | no | yes, readonly | yes | `git diff --check`、只读 plan 输出审查 | 输出实际 update range、source contracts、30m/60m 方案 |
| JM-UPDATE-2C-WRITE-PARQUET | JM raw / standard parquet 写入 | 在授权后写 v2 raw / standard parquet | 数据写入脚本、最小文档 | 不覆盖 v1，不写业务无关代码 | yes | no 或最小 task only | yes | yes | DuckDB row/min/max、文件 checksum | 6 个周期均有 v2 文件且旧版本保留 |
| JM-UPDATE-2D-REGISTER-QUALITY | manifest / checksum / quality / DB 登记 | 生成 manifest、checksum、quality report，并登记 DB | manifest、quality、DB 登记 | 不修改 schema，除非另开任务 | maybe | yes | maybe | yes | DB 查询、quality report 审查 | `market_data_files` / `data_quality_reports` 可追溯 |
| JM-UPDATE-2E-COVERAGE-AUDIT | coverage audit + Web/Data 验收准备 | 审计覆盖、缺口、重复、质量状态 | 审计脚本、报告、任务记录 | 不改前端行为 | read mostly | read mostly | no | yes | coverage report、DuckDB read | 输出新旧版本覆盖和验收准备报告 |
| DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS | active 数据过滤测试 | 补强正式读取边界测试 | 后端测试、必要读取层小修 | 不改数据写入主链路 | no | no | no | yes | pytest targeted | 回测 / Market / Signal 默认只读 active |
| WEB-DATA-3B-DATA-PAGE-SMOKE | Web Data 页面 smoke | 展示最新覆盖和质量状态 | Web/API smoke、必要文档 | 不做 UI 大改 | no | no | no | optional | 浏览器 smoke、控制台检查 | 页面能看到最新覆盖和质量状态 |

## 10. Stage 2-B Prompt 要点

建议进入 Stage 2-B。

Stage 2-B 任务要点：

- 只运行确认过不会写数据、不会写库、不会写 parquet/manifest 的 plan verification。
- 核对 `scripts/rqdata_jm_update_plan.py` 是否读取本地配置文件；如会读取，需用户单独授权后再执行。
- 输出 `latest_available_trading_day`、`update_start_date`、`source_contracts`、`main_contract_segments`、6 个周期的目标 data_version。
- 明确 `30m/60m` 使用 RQData 直取、1m 聚合还是双路径校验。
- 不运行 `rqdata_v1b_jm_asset.py`。
- 不运行任何 sync / asset / ingest 写入脚本。

当前 blocker：

- `30m/60m` 当前已登记资产状态未知。
- 现有 `jm_update_plan.py` 只列出 `1m/5m/15m/1d`。
- 现有 `rqdata_v1b_jm_asset.py` 默认目标只有 `5m/15m/1d` 聚合，加上源 `1m`，且是写入脚本。

## 11. Stage 2-B 只读验证结果

执行时间：2026-07-06

只读安全审查结论：

- `scripts/rqdata_jm_update_plan.py` 只初始化 `RqDataClient`、调用 `build_jm_history_update_plan()` 并向 stdout 输出 JSON。
- `services/quant-api/app/services/rqdata_ingest/jm_update_plan.py` 只调用 `client.trading_dates()` 和 `client.dominant_contracts()`，不调用 parquet、manifest、DB session、quality report 或 sync/asset/ingest 写入入口。
- 脚本会通过现有 `load_project_env()` / `rqdatac.init()` 安全初始化 RQData，但不打印真实凭据。
- 输出中包含推荐写入命令字符串；这些命令本轮没有执行，且 Stage 2-C 前仍需单独授权。

实际运行：

```bash
uv run --project services/quant-api python scripts/rqdata_jm_update_plan.py > /tmp/guiyi-jm-update-plan-verify.json 2> /tmp/guiyi-jm-update-plan-verify.err
```

结果摘要：

| field | value | source |
|---|---|---|
| `latest_available_trading_day` | `2026-07-06` | plan output field `latest_trading_date` |
| `update_start_date` | `2026-01-05` | plan output |
| `update_end_date` | `2026-07-06` | plan output field `latest_trading_date` |
| `target_timeframes` | required: `1m/5m/15m/30m/60m/1d`; current script output: `1m/5m/15m/1d` | Stage 2-A requirement + plan output |
| `source_contracts` | `JM2605`, `JM2609` | plan output |
| `main_contract_segments` | `JM2605`: 2026-01-05 to 2026-04-15, 66 trading days; `JM2609`: 2026-04-16 to 2026-07-06, 54 trading days | plan output |
| `uses_dominant_mapping` | yes | source review + plan output |
| `uses_continuous_contracts` | no | source review |
| `uses_trading_sessions` | no | source review |
| `writes_data` | false | plan output safety + source review |
| `writes_db` | false | plan output safety + source review |
| `writes_parquet` | false | source review |
| `writes_manifest` | false | source review |
| `safety_decision` | safe for readonly plan verification; blocked for write authorization | source review + plan output |

当前脚本输出的 data_version：

| timeframe | data_version | status |
|---|---|---|
| 1m | `rqdata_jm_standard_1m_20260105_20260706_v1` | present, but naming is incremental-window `v1`, not Stage 2-A designed full-window `v2` |
| 5m | `rqdata_jm_standard_5m_20260105_20260706_v1` | present, but naming is incremental-window `v1`, not Stage 2-A designed full-window `v2` |
| 15m | `rqdata_jm_standard_15m_20260105_20260706_v1` | present, but naming is incremental-window `v1`, not Stage 2-A designed full-window `v2` |
| 30m | missing | blocker |
| 60m | missing | blocker |
| 1d | `rqdata_jm_standard_1d_20260105_20260706_v1` | present, but naming is incremental-window `v1`, not Stage 2-A designed full-window `v2` |

`30m/60m` 处理路径：

- 当前计划脚本没有输出 `30m/60m`。
- 当前计划脚本没有说明 `30m/60m` 使用 RQData 直取、`1m` 聚合或双路径校验。
- 因此 `30m/60m` 路径仍为 `missing/blocker`。

写入前 blocker：

- Stage 2-B 任务要求 6 个周期，当前脚本实际只覆盖 4 个周期。
- `30m/60m` 的资产状态和处理路径仍未确认。
- 当前脚本输出的 data_version 是 `20260105_20260706_v1` 增量窗口命名，不符合 Stage 2-A 设计的 `20230103_<latest>_v2` 全窗口新版本命名。
- 输出推荐命令包含写入脚本字符串，Stage 2-C 前必须单独审查并授权，不得直接复制执行。
- JM 历史数据仍未更新；本轮只确认计划，不产生正式数据资产。
