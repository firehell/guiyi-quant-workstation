# Current Task

## Task ID

`SYNC-001-current-project-gpt-handoff`

## 任务名称

汇总当前项目状态，更新给浏览器 GPT 同步的项目文件。

## 背景

用户需要把当前仓库状态同步给浏览器 GPT，用于后续继续做需求分析、任务拆分和 Codex Prompt。仓库当前不是从零设计阶段，必须基于当前代码和最新文档事实整理：

- RQData / Local Standard Parquet 是 V1 active 主链路。
- DATA-001 数据源瘦身已完成，旧 TqSdk / 天勤、交易练习者 active 数据入口已移除。
- 本地工作站已补 `/healthz`、同源 API/WS 解析和 Cloudflare Tunnel + Access 文档。
- RQAlpha / XMA 实验目录存在，但不属于 V1 正式回测报告链路。
- 下一步优先是 RQData 权限与接口能力 PoC，然后才是 JM 数据更新到最新交易日。

## 本轮目标

- 更新 `CURRENT_STATE.md` 和 `PROJECT_SNAPSHOT.md`，形成可直接上传 GPT 的当前状态包。
- 更新 `docs/CODEX_HANDOFF_FOR_CHATGPT.md` 和 `docs/NEXT_STEPS.md`，明确后续任务拆分口径。
- 修正 README 和部分架构文档中残留的过期 V1 文档链接 / legacy 数据入口表述。
- 不修改业务代码、数据库、数据目录、策略逻辑或回测结果。

## 允许修改范围

- `CURRENT_STATE.md`
- `PROJECT_SNAPSHOT.md`
- `README.md`
- `docs/CODEX_HANDOFF.md`
- `docs/CODEX_HANDOFF_FOR_CHATGPT.md`
- `docs/NEXT_STEPS.md`
- `docs/PROJECT_INVENTORY.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `tasks/current.md`

## 禁止修改范围

- 不修改 `services/quant-api/app/` 业务代码。
- 不修改 `apps/quant-web/src/` 前端业务代码。
- 不修改 `packages/quant-core/` 策略代码。
- 不修改数据库 migration。
- 不写数据库。
- 不运行 RQData 下载。
- 不写入或删除 `data/`。
- 不写入 `.env`、账号、密码、Token、API Key、license、交易密钥。
- 不修改历史回测报告。

## 执行模式

- 当前执行文档同步。
- 低风险文档任务，可直接执行。
- 如发现需要业务代码、数据库、数据目录或策略逻辑改动，触发 Gate 并暂停。

## 任务步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 测试命令 | 测试结果 | 风险记录 |
|---|---|---|---|---|---|---|---|
| 0 | done | low | 当前状态核对 | git/docs/tasks/data find | `git status --short --branch`; `find data ...`; 核心文档读取 | passed | 开始前工作区干净；旧 TqSdk / trader 数据查找无输出 |
| 1 | done | low | 更新 GPT 同步入口 | `CURRENT_STATE.md`, `PROJECT_SNAPSHOT.md`, `docs/CODEX_HANDOFF_FOR_CHATGPT.md`, `docs/NEXT_STEPS.md` | 文档检查 | passed | 只改文档，不改业务代码 |
| 2 | done | low | 修正 README / inventory / 架构残留口径 | README 和 docs 小范围 | 链接/文本检查 | passed | 已移除 README 主入口中的不存在 V1 旧文档链接 |
| 3 | done | low | 最终验证和交付摘要 | docs/tasks | `git diff --check`; `git status --short`; targeted rg | passed | 未运行数据下载和数据库写入 |

## Gates

| Gate | 触发条件 | 暂停时必须报告 |
|---|---|---|
| Gate 0 | 准备修改业务代码、策略代码、migration 或数据目录 | 拟修改文件、触发原因、风险和是否需要用户确认 |
| Gate 1 | 需要运行 RQData 下载、写数据库、写 `data/` 或读取/打印真实 licence | 触发原因、命令、风险和确认问题 |
| Gate 2 | 发现当前仓库事实与文档明显冲突且无法仅靠文档收敛 | 冲突点、证据文件、建议处理方式 |

## 验收标准

- [x] `CURRENT_STATE.md` 已更新到当前分支和当前项目事实。
- [x] `PROJECT_SNAPSHOT.md` 可作为 GPT 长期上下文入口。
- [x] `docs/CODEX_HANDOFF_FOR_CHATGPT.md` 可直接上传给 GPT。
- [x] `docs/NEXT_STEPS.md` 明确下一步 RQData PoC 和后续任务顺序。
- [x] README 不再把不存在的旧 V1 文档作为主入口。
- [x] 架构/数据文档不再把旧 TqSdk / 交易练习者写成 active 数据入口。
- [x] 未修改业务代码、数据库、数据目录、策略逻辑或回测报告。
- [x] 运行文档检查命令并记录结果。

## 测试命令

```bash
git status --short --branch
find data -path '*tqsdk*' -o -path '*trader*' -o -path '*Future*'
git diff --check
rg -n "V1_REFACTOR_VNPY_RQDATA|V1B_JM_3Y|V1B1_|V1_FINAL_ACCEPTANCE|Local Legacy Data|LegacyValidationProvider|127 passed|153 passed|501\\.85" README.md CURRENT_STATE.md PROJECT_SNAPSHOT.md docs
```

## 本轮测试结果

- `git status --short --branch`：当前分支 `codex/workstation-cloudflare-healthz`，仅有本轮文档修改。
- `find data -path '*tqsdk*' -o -path '*trader*' -o -path '*Future*'`：无输出。
- `git diff --check`：passed。
- targeted stale keyword `rg`：除任务文件中历史检查命令自引用外，README / 当前状态 / GPT 同步入口未再命中过期 V1 旧文档主入口、旧测试数量或 legacy provider 表述。
- 未运行后端 pytest / 前端 build：本轮只改 Markdown 文档，未改业务代码。
- 未运行 RQData 下载、未写数据库、未写 `data/`。

## 完成后输出要求

```markdown
### 结论
### 修改内容
### 测试与验证
### 风险与未完成项
### 建议下一步
### 协作建议
```
