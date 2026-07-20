# ADR-WS-002: Simplified GitHub + Codex Workstation

日期：2026-07-20

状态：Accepted

任务：`WS-FINAL-CLEANUP-05-CANONICAL-FINAL-SYNC`

Supersedes：`ADR-WS-001-github-native-control-plane.md`

## Context

归一量化本地工作站曾采用 GitHub Native V3 控制平面（ADR-WS-001），并叠加远程 facade、本地兼容执行器、stage 调度、V2 TASK Schema、模型路由与多状态源摘要。后续精简已将工程入口收敛为 `scripts/engineering/*`，并把任务生命周期收敛到 GitHub Issue/PR。继续把 ADR-WS-001 中强制保留 dispatcher / WorkBuddy / CodeBuddy / V2 schema 的条款当作现行决策，会造成文档与真实架构冲突。

业务侧 Stage 6（JM Data Continuity → T3 → T4 → …）与数据/回测/信号 Gate 不变；本 ADR 只裁定工作站控制面与文档状态源。

## Decision

采用精简后的 **GitHub + GPT + Codex + 用户** 工作站模型，作为现行正式决策。

### Current tool model

```text
GPT（浏览器：需求 / 设计 / 审查）
  + GitHub（Issue / PR / main canonical docs）
  + Codex（编码执行）
  + 用户（Plan / 生产写入 / merge / deploy 批准）
```

- Cursor：人工 IDE、调试、最终验收与 Git 操作。
- iPhone ChatGPT：仅可作为 Codex 远程入口，不另建状态源或控制面。
- 正式工程入口：`scripts/engineering/*`（`preflight` / `test.sh` profiles / `check-secrets` / `runtime-health`）。

### Canonical sources

| 源 | 职责 |
|---|---|
| `STATUS.md` | 项目当前状态与 Gate（唯一状态摘要） |
| GitHub Issue / PR | 任务生命周期 |
| `DECISIONS.md` / ADR | 长期决策 |
| `docs/tasks/<TASK_ID>.md` | 仅高风险任务执行契约（按需） |
| 版本化报告 / PR evidence | 运行证据 |

禁止把对话 memory、`.ai/results`、已删除的旧任务池 / GPT 摘要目录当作 active canonical。

### Normal task flow

1. Issue（或明确口头范围）说明目标。
2. 非 `main` 分支 / worktree 开发。
3. `scripts/engineering/preflight.sh` + 定向测试或 `test.sh engineering|docs|backend-health|all-safe`。
4. 开 PR；**不自动 merge**。
5. 普通任务不强制新建 `docs/tasks/<TASK_ID>.md`。

### High-risk flow

适用：策略公式、回测撮合/成本口径、数据库 / migration、数据湖写入、live 表、企业微信真实发送、生产配置。

1. 必须有 GitHub Issue，写清风险与回滚。
2. 必要时保留 `docs/tasks/<TASK_ID>.md`。
3. **真实写入**必须使用业务专用、hash-bound、scope-bound approval packet / Gate（如 JM T3/T4）。没有专用 Gate 就禁止真实写入，先独立设计 Gate。
4. Issue 中用户批准是决策记录，**不能**替代代码层 hash 校验。
5. 禁止未来函数、静默降级数据源、削弱 secret / mount Gate。

### Deleted components

以下组件已退出正式架构，**不恢复**：

- WorkBuddy / CodeBuddy / dispatcher stage 机
- TASK runtime / model router / 旧 `scripts/ai` 与 `scripts/env` 控制面入口
- 旧多状态源与摘要目录（含已删除的 GPT Sources / workstation / workflows archive 导航）
- 通用 `production-write-check.sh`（业务专用 Gate 保留）

### Retained safety principles

- 不自动 push / merge / deploy / 关闭高风险 Issue。
- 不读取、显示或提交凭据；`check-secrets.sh` 默认 fail-closed。
- 环境 / 挂载 / 数据源缺失时 fail-closed。
- 策略、回测、信号禁止未来函数与数据泄露。
- 资金相关计算使用 `Decimal`；交易相关逻辑必须可解释、可回测、可复盘。
- V1 不做无人值守自动实盘；企业微信只做观察提醒。

### Consequences

正向：

- 单一任务生命周期（Issue/PR）与单一项目状态源（`STATUS.md`），减少多摘要漂移。
- 工程 Gate 可 CI 化（`engineering-test.yml`、固定 test profiles）。
- 高风险写入仍由业务专用 hash-bound Gate 保护。

代价：

- 不再提供本地 dispatcher / 远程 facade 自动化编排；人工通过 GitHub + Codex 完成。
- 普通任务不再依赖机器可读 V2 TASK Schema 字段全集。

### Maintenance-only rule

```text
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
```

工作站侧仅维护工程入口与安全 Gate；不重建多入口控制面。`POST_FREEZE_REAL_PILOT_PASSED` / `WORKSTATION_FINAL_CLEANUP_COMPLETE` 仅在 Step 6 Pilot 合并后写入，不由本 ADR 提前宣布。

## References

- `AGENTS.md`
- `docs/DEVELOPMENT.md`
- `DECISIONS.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `TESTING.md`
- `docs/decisions/ADR-WS-001-github-native-control-plane.md`（Superseded）
