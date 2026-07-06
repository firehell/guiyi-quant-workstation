# 当前任务同步：阶段 2-A JM 历史数据更新方案 + 数据源收敛 Gate

## 最新状态

本轮已完成 Stage 2-A docs-only / plan-only 任务同步。核心方案文件为 `docs/JM_HISTORY_UPDATE_PLAN.md`，任务入口为 `tasks/current.md`。

本轮没有运行真实 RQData，没有写 `data/`，没有写数据库，没有写 parquet、manifest、checksum 或 quality report，没有修改业务代码。

下一步建议进入 `JM-UPDATE-2B-PLAN-VERIFY`：只读确认实际最新交易日、主力合约段、6 个周期目标版本、30m/60m 路径和写入前 blocker。

## Stage 2-A 交付文件

- `docs/JM_HISTORY_UPDATE_PLAN.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/PROJECT_SNAPSHOT.md`

## 后续任务拆分

| task_id | title | 状态 |
|---|---|---|
| JM-UPDATE-2B-PLAN-VERIFY | JM update dry-run / plan verification | next |
| JM-UPDATE-2C-WRITE-PARQUET | JM raw / standard parquet 写入 | pending authorization |
| JM-UPDATE-2D-REGISTER-QUALITY | manifest / checksum / quality / DB 登记 | pending authorization |
| JM-UPDATE-2E-COVERAGE-AUDIT | coverage audit + Web/Data 验收准备 | pending |
| DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS | active 数据过滤测试 | pending |
| WEB-DATA-3B-DATA-PAGE-SMOKE | Web Data 页面 smoke | pending |

---

# 当前任务：阶段 1-D 固化 RQData PoC 结论并更新项目状态

## 本轮目标

基于阶段 1-C 的真实只读 PoC 结果，固化阶段 1 结论，统一项目状态文档，并准备进入阶段 2 JM 历史数据更新到最新交易日的 Plan 任务。

本轮只做文档固化，不运行 RQData，不写 `data/`，不写数据库，不写 parquet，不写 manifest，不启动服务，不修改业务代码。

## 任务性质

docs-only status freeze

## 当前分支

`main`

## 允许修改范围

- `docs/RQDATA_POC_REPORT.md`
- `CURRENT_STATE.md`
- `PROJECT_SNAPSHOT.md`
- `docs/NEXT_STEPS.md`
- `docs/ROADMAP.md`
- `tasks/current.md`

## 禁止事项

- 不改业务代码。
- 不改前端代码。
- 不改策略代码。
- 不改回测代码。
- 不新增 migration。
- 不运行 RQData。
- 不运行 JM 更新。
- 不运行任何 sync / asset / ingest 写入脚本。
- 不写数据库。
- 不写 `data/`。
- 不写 parquet 或 manifest。
- 不写 quality report。
- 不启动服务。
- 不打印或记录任何敏感信息。
- 不把 RQData PoC 结论夸大为 JM 数据已经更新。
- 不把接口可用性夸大为实时 1m 入库已经完成。
- 不覆盖或删除当前未跟踪的 1-B PoC 文件。

## 执行步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 验证 |
|---|---|---|---|---|---|
| 0 | done | low | 当前状态核对 | git/docs | `git status --short`; `git branch --show-current` |
| 1 | done | low | 读取阶段 1-C 事实依据 | docs only | `docs/RQDATA_POC_REPORT.md`; `/tmp/guiyi-rqdata-poc-result.md` |
| 2 | done | low | 更新当前状态入口 | docs only | `CURRENT_STATE.md`; `PROJECT_SNAPSHOT.md` |
| 3 | done | low | 更新路线与下一步 | docs only | `docs/NEXT_STEPS.md`; `docs/ROADMAP.md` |
| 4 | done | low | 更新 PoC 报告旧口径 | docs only | `docs/RQDATA_POC_REPORT.md` |
| 5 | done | low | 更新任务记录 | tasks only | `tasks/current.md` |
| 6 | done | low | 最终验证 | no repo writes | `git diff --check`; 文本一致性和敏感形态检查；`git status --short` |

## 阶段 1 固化结论

阶段 1 RQData 权限与接口能力 PoC 已完成，判定为 `PARTIAL`。

可作为阶段 2 依据的事实：

- `rqdatac_import` 通过，版本为 `3.2.5`。
- `rqdata_auth_init` 通过。
- JM 合约目录和 DCE JM 合约列表可用。
- `historical_1d_sample` 和 `historical_1m_sample` 可用，字段包含 OHLCV 和 `open_interest`。
- `frequency_5m_direct`、`frequency_15m_direct`、`frequency_30m_direct`、`frequency_1h_direct` 可用。
- `dominant_mapping`、`contract_multiplier`、`margin`、`commission` 可用。

仍需后续确认的缺口：

- `trading_sessions` 状态为 `pass` 但 `sample_row_count=0`。
- `continuous_contracts` 状态为 `pass` 但 `sample_row_count=0`。
- `ex_factor` 状态为 `pass` 但 `sample_row_count=0`。
- `realtime_snapshot_or_bar` 仍为 `skipped`，当前没有安全 realtime wrapper。
- `invalid_symbol_error` 返回 `ValueError`，属于负向探针结果，不阻塞历史数据更新。

## 验收标准

- [x] `docs/RQDATA_POC_REPORT.md` 不再把 1-C 写成下一步。
- [x] `CURRENT_STATE.md` 和 `PROJECT_SNAPSHOT.md` 已写明阶段 1 完成、阶段 2 next。
- [x] `docs/NEXT_STEPS.md` 和 `docs/ROADMAP.md` 已更新阶段状态。
- [x] 文档保留 JM 数据仍停在 `2025-12-31` 的事实。
- [x] 文档没有把 PoC 结论写成 JM 数据已更新、active 数据链路已完成或实时 1m 入库已完成。
- [x] 当前未跟踪的 1-B PoC 脚本和测试文件未被覆盖或删除。

## 已验证命令

```bash
git status --short
git branch --show-current
git diff --check
旧阶段 1 口径检查
敏感形态检查
误表述检查
git status --short
```

当前结果：

- `git diff --check`：通过。
- 旧阶段 1 口径检查：无命中。
- 敏感形态检查：仅命中文档中的安全禁令文字，例如“不读取、打印、记录 RQData 账号、密码、license、token 或 key”和 `prints_secret_values=false`，未发现真实值或赋值形态。
- 误表述检查：仅命中否定句或禁止项，未发现把 JM 数据更新、active 数据链路、实时 1m 入库、企业微信或 `signal_events` 写成已完成能力。
- `git status --short`：仅显示本轮允许文档变更，以及阶段 1-B 已存在的未跟踪 PoC 脚本和测试文件。

## 不运行的测试

```bash
uv run --project services/quant-api python scripts/rqdata_realtime_poc.py --run-readonly
uv run --project services/quant-api python scripts/rqdata_v1b_jm_asset.py
uv run --project services/quant-api pytest -q
cd apps/quant-web && pnpm build
```

原因：

- 本轮只固化文档状态，不运行 RQData，不修改后端服务逻辑、前端代码、策略、回测或数据库。
- 全量测试、前端构建和浏览器验收不属于 1-D docs-only 最小验收路径。

## 下一步

阶段 2：JM 历史数据更新到最新交易日的方案和执行任务。

阶段 2 建议：

- 开新 Codex 会话。
- 使用 Plan 模式。
- 先明确更新范围、输出路径、manifest / checksum、quality_status、最小质量检查和回滚策略。
- 不直接运行 `rqdata_v1b_jm_asset.py` 或 sync 写入脚本，直到任务包明确允许。
