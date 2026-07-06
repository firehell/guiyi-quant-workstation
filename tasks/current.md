# 当前任务：Stage 2-B JM 历史数据更新只读计划验证

生成时间：2026-07-06
任务性质：readonly RQData plan verification / docs update

## 本轮目标

完成 `JM-UPDATE-2B-PLAN-VERIFY`：只读确认 JM 历史数据更新到最新交易日前的实际范围、最新交易日、主力合约段、周期覆盖、目标 data_version 和写入前 blocker。

本轮不是数据写入任务。

## 当前结论

- Stage 2-B 只读验证已完成。
- `scripts/rqdata_jm_update_plan.py` 通过源码审查：不写 `data/`，不写数据库，不写 parquet、manifest、checksum 或 quality report，不调用 sync / asset / ingest 写入脚本。
- 脚本会通过现有 `load_project_env()` / `rqdatac.init()` 安全初始化 RQData，但不打印真实凭据。
- 只读计划输出保存到仓库外 `/tmp/guiyi-jm-update-plan-verify.json`。
- 最新可用交易日：`2026-07-06`。
- 增量起始交易日：`2026-01-05`。
- 主力合约段：`JM2605`、`JM2609`。
- 当前脚本只覆盖 `1m/5m/15m/1d` 四个周期，缺少目标要求中的 `30m/60m`。
- 当前脚本输出 data_version 为增量窗口 `v1` 命名，不符合 Stage 2-A 设计的全窗口 `v2` 命名。
- JM 历史数据仍未更新；不得进入写 parquet / manifest / DB。

## 当前分支

`main`

## 允许范围

- 更新 `docs/JM_HISTORY_UPDATE_PLAN.md`。
- 更新 `docs/gpt/CURRENT_STATE.md`。
- 更新 `docs/gpt/NEXT_STEPS.md`。
- 更新 `docs/gpt/tasks_current.md`。
- 更新 `tasks/current.md`。
- 只允许把临时验证输出写到仓库外 `/tmp/`。

## 禁止范围

- 不修改后端业务代码。
- 不修改前端代码。
- 不修改策略代码。
- 不修改回测代码。
- 不新增 migration。
- 不运行写入类 sync / asset / ingest 脚本。
- 不写数据库。
- 不写 `data/`。
- 不写 parquet、manifest、checksum 或 quality report。
- 不启动后端或前端服务。
- 不自动 commit，不 push。
- 不把 JM 数据更新、实时 1m 入库、`signal_events` 或企业微信提醒写成已完成。

## 只读安全审查

| item | result |
|---|---|
| `scripts/rqdata_jm_update_plan.py` | 只构造 `RqDataClient`、调用 plan builder、向 stdout 输出 JSON |
| `services/quant-api/app/services/rqdata_ingest/jm_update_plan.py` | 只调用 `trading_dates()` 和 `dominant_contracts()`，生成 dict |
| DB 写入 | 未发现 |
| `data/` 写入 | 未发现 |
| parquet / manifest / checksum / quality report | 未发现 |
| sync / asset / ingest 写入脚本执行 | 未发现；仅输出推荐命令字符串 |
| 凭据打印 | 未发现 |
| `30m/60m` 支持 | 未覆盖 |

## 只读验证输出

| field | value |
|---|---|
| `latest_available_trading_day` | `2026-07-06` |
| `update_start_date` | `2026-01-05` |
| `update_end_date` | `2026-07-06` |
| `source_contracts` | `JM2605`, `JM2609` |
| `main_contract_segments` | `JM2605`: 2026-01-05 to 2026-04-15, 66 trading days; `JM2609`: 2026-04-16 to 2026-07-06, 54 trading days |
| `target_timeframes` | required: `1m/5m/15m/30m/60m/1d`; current script output: `1m/5m/15m/1d` |
| `uses_dominant_mapping` | yes |
| `uses_continuous_contracts` | no |
| `uses_trading_sessions` | no |
| `writes_data` | false |
| `writes_db` | false |
| `writes_parquet` | false |
| `writes_manifest` | false |
| `safety_decision` | safe for readonly plan verification; blocked for write authorization |

## 当前脚本输出的 data_version

| timeframe | data_version | status |
|---|---|---|
| 1m | `rqdata_jm_standard_1m_20260105_20260706_v1` | present, but not full-window `v2` |
| 5m | `rqdata_jm_standard_5m_20260105_20260706_v1` | present, but not full-window `v2` |
| 15m | `rqdata_jm_standard_15m_20260105_20260706_v1` | present, but not full-window `v2` |
| 30m | missing | blocker |
| 60m | missing | blocker |
| 1d | `rqdata_jm_standard_1d_20260105_20260706_v1` | present, but not full-window `v2` |

## 已运行命令

```bash
git status --short
git branch --show-current
find . -maxdepth 4 \( -name "CURRENT_STATE.md" -o -name "PROJECT_SNAPSHOT.md" -o -name "RQDATA_POC_REPORT.md" -o -name "JM_HISTORY_UPDATE_PLAN.md" -o -name "NEXT_STEPS.md" -o -name "tasks_current.md" -o -name "current.md" \)
sed -n '1,240p' docs/gpt/CURRENT_STATE.md
sed -n '1,320p' docs/JM_HISTORY_UPDATE_PLAN.md
sed -n '1,260p' tasks/current.md
sed -n '1,260p' docs/gpt/RQDATA_POC_REPORT.md
sed -n '1,260p' docs/gpt/NEXT_STEPS.md
sed -n '1,320p' scripts/rqdata_jm_update_plan.py
sed -n '1,420p' services/quant-api/app/services/rqdata_ingest/jm_update_plan.py
sed -n '1,360p' services/quant-api/tests/test_rqdata_jm_update_plan.py
sed -n '1,340p' services/quant-api/app/services/rqdata_ingest/client.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_jm_update_plan.py
uv run --project services/quant-api python scripts/rqdata_jm_update_plan.py > /tmp/guiyi-jm-update-plan-verify.json 2> /tmp/guiyi-jm-update-plan-verify.err
wc -c /tmp/guiyi-jm-update-plan-verify.err
rg -n "RQDATA_|RQDATAC|PASSWORD|TOKEN|SECRET|KEY|LICENSE|webhook|http://|https://|rqdatad" /tmp/guiyi-jm-update-plan-verify.json /tmp/guiyi-jm-update-plan-verify.err
git diff --check
```

## 验证结果

- `git status --short`：执行前工作区干净。
- `git branch --show-current`：`main`。
- `CURRENT_STATE.md`、`RQDATA_POC_REPORT.md`、`NEXT_STEPS.md` 的实际路径位于 `docs/gpt/`。
- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_jm_update_plan.py`：`2 passed in 0.33s`。
- `scripts/rqdata_jm_update_plan.py`：执行成功，stdout 写入 `/tmp/guiyi-jm-update-plan-verify.json`。
- `/tmp/guiyi-jm-update-plan-verify.err`：0 bytes。
- 临时输出敏感形态检查：无命中。
- `git diff --check`：通过。

## 写入前 blocker

- 计划脚本未覆盖 `30m/60m`。
- 计划脚本未说明 `30m/60m` 使用 RQData 直取、`1m` 聚合或双路径校验。
- 计划脚本输出的 data_version 是 `20260105_20260706_v1` 增量窗口命名，不符合 Stage 2-A 的 `20230103_<latest>_v2` 全窗口新版本设计。
- 输出中推荐命令包含真实写入脚本字符串，但本轮没有执行；Stage 2-C 前必须单独审查和授权。

## 下一步建议

进入 `JM-UPDATE-2B-FIX-PLAN-GAPS`：

- 补齐 plan 脚本或单独计划文档，使 6 个周期 `1m/5m/15m/30m/60m/1d` 全部明确。
- 明确 `30m/60m` 路径：RQData 直取、`1m` 聚合或双路径校验。
- 将目标 data_version 收敛为不覆盖旧版本的全窗口 `v2` 命名。
- 完成后再决定是否进入 `JM-UPDATE-2C-WRITE-PARQUET`。

## GPT 同步说明

本轮应同步给浏览器 GPT 的最新文件：

- `docs/JM_HISTORY_UPDATE_PLAN.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/tasks_current.md`
- `tasks/current.md`
