# 当前任务：阶段 2-A JM 历史数据更新方案 + 数据源收敛 Gate

生成时间：2026-07-06
任务性质：docs-only / plan-only

## 本轮目标

为“阶段 2：JM 历史数据更新到最新交易日”完成执行前设计，不运行真实写入。

本轮核心产物：

- `docs/JM_HISTORY_UPDATE_PLAN.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/PROJECT_SNAPSHOT.md`

## 当前结论

- 阶段 2-A 是方案设计任务，不是数据更新执行任务。
- 当前 JM 正式研究数据仍停在 `2025-12-31`。
- 本轮没有运行真实 RQData。
- 本轮没有写 `data/`。
- 本轮没有写数据库。
- 本轮没有写 parquet、manifest、checksum 或 quality report。
- 本轮没有修改后端、前端、策略、回测或 migration。
- 建议下一步进入 `JM-UPDATE-2B-PLAN-VERIFY`。

## 当前分支

`main`

## 允许范围

- 新增 `docs/JM_HISTORY_UPDATE_PLAN.md`。
- 新建或更新 `tasks/current.md`。
- 更新 GPT 同步包：
  - `docs/gpt/CURRENT_STATE.md`
  - `docs/gpt/tasks_current.md`
  - `docs/gpt/NEXT_STEPS.md`
  - `docs/gpt/PROJECT_SNAPSHOT.md`

## 禁止范围

- 不修改后端业务代码。
- 不修改前端代码。
- 不修改策略代码。
- 不修改回测代码。
- 不新增 migration。
- 不运行真实 RQData。
- 不运行 JM 更新。
- 不运行 sync / asset / ingest 写入脚本。
- 不写数据库。
- 不写 `data/`。
- 不写 parquet、manifest、checksum 或 quality report。
- 不启动后端或前端服务。
- 不读取本地敏感配置文件。
- 不自动 commit，不 push。
- 不把 JM 数据执行更新、实时 1m 入库、信号事件化或通知能力写成已完成。

## active 数据源 Gate

正式 active 入口必须满足：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先使用：

```text
quality_status = "passed"
```

`validation`、`legacy_reference`、`candidate` 不得进入正式回测、默认 Market API 或 signal scanner 输入。

## 后续任务

| task_id | 标题 | 结论 |
|---|---|---|
| JM-UPDATE-2B-PLAN-VERIFY | JM update dry-run / plan verification | 下一步建议执行，只读确认实际范围 |
| JM-UPDATE-2C-WRITE-PARQUET | JM raw / standard parquet 写入 | 需要用户明确授权写文件 |
| JM-UPDATE-2D-REGISTER-QUALITY | manifest / checksum / quality / DB 登记 | 需要用户明确授权写 DB |
| JM-UPDATE-2E-COVERAGE-AUDIT | coverage audit + Web/Data 验收准备 | 在 2C/2D 后执行 |
| DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS | active 数据过滤测试 | 后续补强读取边界 |
| WEB-DATA-3B-DATA-PAGE-SMOKE | Web Data 页面 smoke | 数据完成后再验收 |

## 已运行命令

```bash
git status --short --branch
git branch --show-current
find . -maxdepth 4 \( -name "CURRENT_STATE.md" -o -name "PROJECT_SNAPSHOT.md" -o -name "RQDATA_POC_REPORT.md" -o -name "ROADMAP.md" -o -name "NEXT_STEPS.md" -o -name "AI_DEVELOPMENT_WORKFLOW.md" -o -name "CODEX_HANDOFF_FOR_CHATGPT.md" -o -name "tasks_current.md" -o -name "current.md" \) | sort
sed -n '1,220p' docs/gpt/CURRENT_STATE.md
sed -n '1,240p' docs/gpt/tasks_current.md
sed -n '1,260p' docs/gpt/NEXT_STEPS.md
sed -n '1,240p' docs/gpt/PROJECT_SNAPSHOT.md
git diff --check
文本安全检查
误表述检查
排除 Git hunk header 后的误表述复核
```

## 验证结果

- `git branch --show-current`：`main`。
- `find ...`：确认当前同步文件位于 `docs/gpt/`，并已新建 `tasks/current.md`。
- `git diff --check`：通过，无空白错误。
- 文本安全检查：无输出。
- 误表述检查：用户指定命令只输出一行 Git hunk header `@@ ... V1 不自动下单。`，属于未改动上下文，不是新增/删除正文。
- 补充误表述检查：排除 hunk header 后无输出。
- `git status --short`：仅显示本轮文档变更和新建文档；没有业务代码、数据文件、parquet、manifest 或 DB 变更。

## 未运行命令及原因

```bash
uv run --project services/quant-api python scripts/rqdata_jm_update_plan.py
uv run --project services/quant-api python scripts/rqdata_v1b_jm_asset.py
uv run --project services/quant-api pytest -q
cd apps/quant-web && pnpm build
```

原因：

- 本轮只做文档和任务状态。
- `scripts/rqdata_jm_update_plan.py` 会构造 RQData client，Stage 2-B 前需单独确认执行边界。
- `scripts/rqdata_v1b_jm_asset.py` 是真实写入脚本，本轮禁止运行。
- 未修改业务代码或前端代码，不需要后端测试、前端构建或浏览器验收。

## 验收标准

- [x] 新增 `docs/JM_HISTORY_UPDATE_PLAN.md`。
- [x] 新建 `tasks/current.md`。
- [x] 更新 `docs/gpt` 同步包。
- [x] 明确 JM 更新范围设计。
- [x] 明确输出路径设计。
- [x] 明确 data_version 设计。
- [x] 明确 manifest / checksum / quality report 设计。
- [x] 明确 active 数据源收敛 Gate。
- [x] 明确质量检查清单。
- [x] 明确回滚策略。
- [x] 拆出 Stage 2-B / 2C / 2D / 2E / 3A / 3B 后续任务。
- [x] 不运行真实 RQData。
- [x] 不写 `data/`。
- [x] 不写数据库。
- [x] 不写 parquet 或 manifest。
- [x] 不修改业务代码。

## GPT 同步说明

本轮应同步给浏览器 GPT 的最新文件：

- `docs/JM_HISTORY_UPDATE_PLAN.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/PROJECT_SNAPSHOT.md`
