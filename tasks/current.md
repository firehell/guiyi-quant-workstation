# 当前任务：阶段 1-A RQData PoC 审计与报告模板

## 本轮目标

审计当前仓库中 RQData 相关代码、依赖、配置、脚本和测试，建立 RQData PoC 报告模板。

本轮只做文档审计和任务记录，不运行 RQData，不读取真实凭据，不写 `data/`，不写数据库，不启动服务。

## 任务性质

docs-only / read-only audit

## 当前分支

`main`

本轮只修改文档和任务文件，不修改业务代码。

## 允许修改范围

- `docs/RQDATA_POC_REPORT.md`
- `tasks/current.md`

## 禁止事项

- 不改业务代码。
- 不改前端代码。
- 不改策略代码。
- 不改回测代码。
- 不新增 migration。
- 不运行 RQData。
- 不写数据库。
- 不写 `data/`。
- 不启动服务。
- 不做浏览器验收。
- 不写 `.env`、账号、密码、Token、API Key、license、企业微信通知地址或交易密钥。
- 不读取、打印、记录 RQData 账号、密码、license、token 或 key。
- 不把阶段 1 写成已经通过。
- 不把 JM 数据更新、实时 1m 入库、企业微信提醒、`signal_events`、Cloudflare Access 部署写成已完成能力。

## 执行步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 验证 |
|---|---|---|---|---|---|
| 0 | done | low | 当前状态核对 | git/docs | `git status --short`; `git branch --show-current` |
| 1 | done | low | 读取项目事实依据 | docs/tasks | `AGENTS.md`; `tasks/current.md`; `PROJECT_SNAPSHOT.md`; `CURRENT_STATE.md`; `docs/NEXT_STEPS.md`; `docs/ROADMAP.md`; `docs/CODEX_HANDOFF_FOR_CHATGPT.md`; `docs/ARCHITECTURE.md`; `docs/AI_DEVELOPMENT_WORKFLOW.md`; `docs/PROJECT_INSTRUCTIONS_COMPACT.md` |
| 2 | done | low | 审计 RQData 代码、依赖、脚本和测试 | read-only | `services/quant-api/app/data_sources/`; `services/quant-api/app/services/rqdata_ingest/`; `services/quant-api/pyproject.toml`; `services/quant-api/uv.lock`; `scripts/`; `services/quant-api/tests/` |
| 3 | done | low | 运行隔离测试 | no repo writes | `uv run --project services/quant-api pytest -q ...` |
| 4 | done | low | 更新 RQData PoC 报告模板 | `docs/RQDATA_POC_REPORT.md` | 文档 diff |
| 5 | done | low | 更新当前任务记录 | `tasks/current.md` | 文档 diff |
| 6 | done | low | 最终验证 | docs/tasks | `git diff --check`; `rg` 文本检查；`git status --short` |

## 验收标准

- [x] `docs/RQDATA_POC_REPORT.md` 已建立阶段 1-A 审计与报告模板。
- [x] `tasks/current.md` 已更新为阶段 1-A 当前任务。
- [x] 报告包含 Status、Scope and Non-goals、Dependency and Credential Boundary、Code Inventory、RQData Capability Matrix、Script Matrix、Existing Test Coverage、Risks and Gaps、Next Stage 1-B Recommendation。
- [x] 报告明确本轮没有运行 RQData，也没有验证真实权限。
- [x] 报告区分代码已有入口和真实权限未验证。
- [x] 报告列明 sync/audit/field_audit 脚本的写入或读取风险。
- [x] 只修改允许范围。
- [x] 文档中没有真实账号、密码、Token、API Key、license 或通知地址。
- [x] 文档没有把阶段 1、JM 数据更新、实时 1m 入库、企业微信提醒或 `signal_events` 写成已完成。
- [x] 没有修改业务代码。
- [x] 没有运行 RQData。
- [x] 没有写数据库。
- [x] 没有写 `data/`。
- [x] 没有新增依赖。
- [x] 没有新增 migration。

## 测试命令

```bash
git status --short
git branch --show-current
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_client.py services/quant-api/tests/test_rqdata_structured_ingest.py services/quant-api/tests/test_rqdata_jm_update_plan.py services/quant-api/tests/test_rqdata_sync_common.py services/quant-api/tests/test_data_sources.py services/quant-api/tests/test_market_data_reader.py
git diff --check
git diff --stat
git diff -- docs/RQDATA_POC_REPORT.md tasks/current.md
```

额外文本检查：

- 误表述检查：确认报告和任务文件没有把未完成能力写成已完成。
- 敏感形态检查：确认报告和任务文件没有 webhook URL 或密钥赋值形态。

## 不运行的测试

```bash
cd apps/quant-web && pnpm build
uv run --project services/quant-api pytest -q
```

原因：本轮只修改 Markdown 文档和任务入口，未修改业务代码、前端代码、策略、回测或数据库；已运行 RQData 相关隔离测试子集。

## 下一步

阶段 1-B：真实 RQData 只读权限与字段 PoC。

阶段 1-B 建议先确认只读命令、凭据环境读取边界、脱敏输出格式和输出目录策略。默认不写 `data/`，不写数据库，不运行真实数据写入任务，不打印 license。
