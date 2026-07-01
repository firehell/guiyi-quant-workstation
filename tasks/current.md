# Current Task

## Task ID

`20260701-stage0-project-context`

## 任务名称

阶段 0：项目上下文和协作规则收敛。

## 背景

当前项目已经确立 RQData / Local Standard Parquet 为 V1 主数据源，并已具备 FastAPI、Vue Web、DuckDB、PostgreSQL、vn.py 回测、报告入库、K线 marker、信号扫描和复盘 note 等基础闭环能力。

上一轮 `20260630-su-bing-daily-score2of4` 策略任务已经完成，`v0.3.0-daily-score2of4` trusted excluding cross-contract 指标为负，不能作为模拟盘、实盘或参数优化依据。当前需要把项目事实、协作规则和下一阶段顺序整理到文档中，避免后续任务继续停留在旧策略实现上下文。

## 本轮目标

- 新增精简协作指令文档。
- 更新 ChatGPT / Codex 协作流程。
- 更新下一阶段任务顺序。
- 更新项目快照、当前状态、ChatGPT 交接和路线图。
- 将 `tasks/current.md` 切换为阶段 0 文档任务包。
- 本轮只修改文档和任务文件，不修改业务代码。

## 当前事实依据

事实优先级：

1. 当前仓库代码。
2. `PROJECT_SNAPSHOT.md`
3. `CURRENT_STATE.md`
4. `docs/CODEX_HANDOFF_FOR_CHATGPT.md`
5. `docs/STRATEGY_CURRENT_STATE.md`
6. `docs/NEXT_STEPS.md`
7. `docs/AI_DEVELOPMENT_WORKFLOW.md`
8. `docs/ROADMAP.md`
9. 旧聊天记录，仅作历史参考。

当前主链路：

```text
RQData / Local Standard Parquet
-> DuckDB
-> vn.py CTA BacktestingEngine
-> ResultConverter
-> PostgreSQL
-> FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察 / 交易复盘
```

## 允许修改范围

- `PROJECT_SNAPSHOT.md`
- `CURRENT_STATE.md`
- `docs/CODEX_HANDOFF_FOR_CHATGPT.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `docs/ROADMAP.md`
- `docs/PROJECT_INSTRUCTIONS_COMPACT.md`
- `tasks/current.md`

## 禁止修改范围

- `services/`
- `apps/`
- `packages/`
- `strategies/`
- `scripts/`
- `data/`
- `backtests/`
- `alembic/`
- `docker-compose*`
- `.env*`
- `pyproject.toml`
- `package.json`
- `pnpm-lock.yaml`
- `uv.lock`

本轮禁止：

- 修改业务代码、后端 API、前端页面、策略代码、回测代码或数据库 migration。
- 运行 RQData 拉数。
- 运行会写数据库的脚本。
- 写入 `data/`。
- 接入实时行情、企业微信 webhook、模拟盘或实盘接口。
- 写入账号、密码、Token、API Key、license、webhook URL 或交易密钥。

## 执行模式

- 当前为文档 / 项目上下文任务，可直接执行。
- 修改前必须确认不在 `main` 上执行文档更新。
- 如果当前在 `main`，先创建或切换到 `codex/stage0-project-context`。
- 低风险文档收敛可继续；触发 Gate 必须暂停。

## 任务步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 测试命令 | 测试结果 | 风险记录 |
|---|---|---|---|---|---|---|---|
| 0 | done | low | 分支初始化 | git 状态 | `git status --short`; `git branch --show-current` | 当前分支 `codex/stage0-project-context` | 已避免在 `main` 上修改 |
| 1 | done | low | 新增精简协作指令 | `docs/PROJECT_INSTRUCTIONS_COMPACT.md` | 文档审查 | 已新增 | 不写敏感信息 |
| 2 | done | low | 收敛 workflow / next steps / handoff / roadmap / snapshot / state | 项目文档 | `git diff --stat` | 已更新 | 只写当前事实和计划，不写未完成能力为已完成 |
| 3 | done | low | 更新当前任务文件 | `tasks/current.md` | 文档审查 | 已切换为阶段 0 任务 | 后续任务不再停留在旧 score2of4 实现 |
| 4 | pending | low | 最终验证 | git / find / diff | 待执行 | 待执行 | 不运行后端/前端测试 |

## Gates

| Gate | 触发条件 | 暂停时必须报告 |
|---|---|---|
| Gate 0 | 仍在 `main` 且准备改文件 | 当前分支、工作区状态、建议分支 |
| Gate 1 | 出现大量非本轮业务代码改动 | 改动文件、是否相关、继续风险 |
| Gate 2 | 需要修改禁止范围文件 | 触发原因、拟修改文件、风险和确认问题 |
| Gate 3 | 需要运行 RQData、写 `data/`、写数据库、读取凭据或接入 webhook | 触发原因、风险和需要用户确认的问题 |
| Gate 4 | 需要把实时入库、企业微信、TDX XMA、trusted metrics 闭环写成已完成事实 | 当前依据、建议改为“待做/计划”的文本 |

## 验收标准

- [x] 项目有精简版协作指令文档 `docs/PROJECT_INSTRUCTIONS_COMPACT.md`。
- [x] `docs/AI_DEVELOPMENT_WORKFLOW.md` 与精简协作规则一致。
- [x] `docs/NEXT_STEPS.md` 已更新为阶段 0 后的顺序任务表。
- [x] `PROJECT_SNAPSHOT.md` 反映当前主链路和项目边界。
- [x] `CURRENT_STATE.md` 反映本轮文档任务状态。
- [x] `docs/CODEX_HANDOFF_FOR_CHATGPT.md` 能让新 ChatGPT 项目正确接手。
- [x] `docs/ROADMAP.md` 没有把未完成能力写成已完成事实。
- [x] `tasks/current.md` 已更新为阶段 0 任务。
- [x] 没有业务代码修改。
- [x] 没有 `data/` 修改。
- [x] 没有数据库修改。
- [x] 没有真实敏感信息。

## 测试命令

必须运行：

```bash
git status --short
git branch --show-current
git diff --stat
find . -maxdepth 3 \( -name "PROJECT_SNAPSHOT.md" -o -name "CURRENT_STATE.md" -o -name "ROADMAP.md" -o -name "CODEX_HANDOFF_FOR_CHATGPT.md" -o -name "STRATEGY_CURRENT_STATE.md" -o -name "NEXT_STEPS.md" -o -name "AI_DEVELOPMENT_WORKFLOW.md" -o -name "PROJECT_INSTRUCTIONS_COMPACT.md" -o -path "./tasks/current.md" \)
```

可选：

```bash
markdownlint "**/*.md"
```

如果仓库没有配置 markdown lint，不新增依赖。

## 浏览器验收

- 是否需要 Browser/Chrome：否。
- 页面地址：不涉及。
- 操作路径：不涉及。
- 原因：本轮只改文档和任务文件，不改前端页面。

## 完成后输出格式

```markdown
## 本轮目标
## 修改摘要
## 变更文件
## 当前项目状态摘要
## 运行命令
## 测试命令
## 测试结果
## 浏览器验收
## 风险与后续 TODO
## 建议上传给 ChatGPT 项目的文件
```

## 下一步建议

阶段 1：RQData 权限与接口能力 PoC。

- 推荐执行模式：Plan 模式。
- 建议新 Codex 会话：是。
- 需要 checkpoint：是。
- 禁止写入 `data/` 和数据库，除非下一轮 Prompt 明确允许。
- 目标：只读确认 RQData 本地环境、权限、可用接口、合约/分钟数据/交易参数字段能力，并输出后续数据链路任务设计。
