# 开发流程

更新时间：2026-07-20

本文件是归一量化**唯一开发流程**说明。旧的 WorkBuddy / CodeBuddy / 双入口 / L0L1L2 / 模型路由长文已退出正式架构，历史见 `docs/archive/`（Step 3 后）。

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
4. 小步实现；跑定向测试 / `scripts/engineering/test.sh`。
5. 开 PR 或交用户审查；**不自动 merge**。
6. 不强制新建 `docs/tasks/<TASK_ID>.md`。

### 高风险任务

适用：策略公式、回测撮合/成本口径、数据库 / migration、数据湖写入、live 表、企业微信真实发送、生产配置。

1. 必须有 GitHub Issue，并写清风险与回滚。
2. 必要时保留 `docs/tasks/<TASK_ID>.md` 作为执行契约。
3. **生产写入**须用户显式确认（`scripts/engineering/production-write-check.sh`，Step 4 起）。
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

已退出 active：`CODEX_TASKS.md`（deprecated 指针）、`tasks/current.md`（兼容指针）、WorkBuddy memory、控制面 stage 状态机。

## 4. 工程入口（推荐）

| 脚本 | 职责 |
|---|---|
| `scripts/engineering/preflight.sh` | 只读环境 / 分支 / 脏树提示 |
| `scripts/engineering/test.sh` | 安全测试聚合（拒绝 push/merge 等） |
| `scripts/engineering/check-secrets.sh` | secret 扫描（不打印真值） |
| `scripts/engineering/runtime-health.sh` | 只读 runtime 探针 |
| `scripts/engineering/production-write-check.sh` | 生产写入确认 fail-closed |

```bash
bash scripts/engineering/preflight.sh --json
bash scripts/engineering/check-secrets.sh
bash scripts/engineering/test.sh
bash scripts/engineering/runtime-health.sh --json
bash scripts/engineering/production-write-check.sh --action demo   # expect fail without confirm
```

旧入口 `scripts/ai/dispatch_task.sh`、`workbuddy_task.sh`、`route_task.sh` 等：**已删除**。勿再调用；历史见 `docs/archive/workstation/`。

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
5. 任务相关：`docs/DATA_CENTER.md` / `ARCHITECTURE.md` / `BACKTEST_ENGINE.md` / `SIGNAL_EVENTS.md` 或对应 Issue

## 7. 工作站模式

```text
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
```

归档：`docs/archive/workstation/`（含 inventory、Pilot、final report）。
