# 开发流程

更新时间：2026-07-20

本文件是归一量化**唯一开发流程**说明。旧多入口控制面 / 双入口 / 分级路由长文已退出正式架构（Git 历史可查）。

## 1. 工具模型

```text
GPT（浏览器，需求/设计/审查）
  + GitHub（Issue / PR / canonical docs）
  + Codex（编码执行）
  + 用户（Plan / 生产写入 / merge / deploy 批准）
```

- Cursor：人工 IDE、调试、最终验收与 Git 操作。
- iPhone ChatGPT：仅 Codex 远程入口，不另建状态源。
- 禁止把对话 memory、`.ai/results`、已废弃任务池当作项目事实源。

## 2. 普通任务 vs 高风险任务

### 普通任务（低–中风险）

适用：文档、前端小修、测试补全、只读探针、非策略公式的小重构。

1. 用 GitHub Issue（或口头确认）说明目标与范围。
2. 在非 `main` 分支 / worktree 开发。
3. 运行 `scripts/engineering/preflight.sh`（Step 4 起；此前可用 `git status` + 本地健康检查）。
4. 小步实现；跑定向测试 / `scripts/engineering/test.sh engineering`（或 `all-safe`）。
5. 开 PR 或交用户审查；**不自动 merge**。
6. 不强制新建 `docs/tasks/<TASK_ID>.md`。

### 高风险任务

适用：策略公式、回测撮合/成本口径、数据库 / migration、数据湖写入、live 表、企业微信真实发送、生产配置。

1. 必须有 GitHub Issue，并写清风险与回滚。
2. 必要时保留 `docs/tasks/<TASK_ID>.md` 作为执行契约。
3. **真实写入**必须使用业务专用、hash-bound、scope-bound approval packet / Gate；没有专用 Gate 就禁止真实写入，先独立设计 Gate。Issue 中用户批准是决策记录，但不能替代代码层 hash 校验。通用 `production-write-check.sh` 已删除（JM T3/T4 等业务 Gate 不变）。
4. 先 Plan / 设计审查，用户批准后再 Dev。
5. 禁止未来函数、静默降级数据源、削弱 secret / mount Gate。
6. 交付必须含：变更文件、测试命令与结果、风险、未完成项。

## 3. 状态源

| 源 | 用途 |
|---|---|
| `STATUS.md` | 项目当前 Gate / 能力 |
| GitHub Issue / PR | 任务生命周期 |
| `DECISIONS.md` | 长期决策 |
| `docs/tasks/*` | 高风险契约（按需） |
| 版本化报告 / PR | 证据 |

已退出 active：旧任务池 / 旁路摘要 / 控制面 stage 状态机（已从文档树删除）。

## 4. 工程入口（推荐）

| 脚本 | 职责 |
|---|---|
| `scripts/engineering/preflight.sh` | 只读环境 / 分支 / 脏树提示（`--strict`：本地 main 或 dirty 失败；`--ci`：跳过「必须在 feature branch」，仍阻断 dirty；不削弱 secret） |
| `scripts/engineering/test.sh` | 固定 profile 测试（`engineering` / `docs` / `backend-health` / `all-safe`）；禁止自由 shell |
| `scripts/engineering/check-secrets.sh` | secret 扫描（默认 fail-closed；不打印真值；CI 禁用 `--warn-only`） |
| `scripts/engineering/runtime-health.sh` | 只读 `/health` JSON 契约探针 |

```bash
bash scripts/engineering/preflight.sh --json
bash scripts/engineering/check-secrets.sh
bash scripts/engineering/test.sh engineering
bash scripts/engineering/runtime-health.sh --json

# Makefile
make engineering-preflight
make engineering-test
make engineering-secrets
# CI: make engineering-ci   # 或 ENGINEERING_PREFLIGHT_ARGS=--ci
```

高风险真实写入：业务专用、hash-bound、scope-bound approval packet / Gate；没有专用 Gate 就禁止真实写入。

旧入口（如历史 `scripts/ai/*` 调度脚本等）：**已删除**。勿再调用。

## 5. Fail-closed 原则

- 缺环境变量、外置盘、数据挂载：失败并报告，不自动创建或切换降级源。
- 测试命令拒绝 `git push/merge`、危险 sandbox、管道写破坏。
- 不自动关闭 GitHub Issue/PR；清理清单仅建议。
- 企业微信默认 preview；真实发送须用户确认。

## 6. 推荐阅读顺序（接手）

1. `STATUS.md`
2. `AGENTS.md`
3. 本文件
4. `PROJECT_SOURCE.md`
5. `DECISIONS.md`
6. 任务相关：`docs/DATA_CENTER.md` / `ARCHITECTURE.md` / `BACKTEST_ENGINE.md` / `SIGNAL_EVENTS.md` 或对应 Issue/PR

## 7. 工作站模式

```text
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
```

工程入口：`scripts/engineering/*`。现行 ADR：`docs/decisions/ADR-WS-002-simplified-github-codex-workstation.md`。不重建多入口控制面。
