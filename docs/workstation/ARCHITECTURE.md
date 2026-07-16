# AI 工作站架构

更新时间：2026-07-14

> 本文描述 **AI 协作控制平面**，不重复量化业务架构。业务链路见 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)。

## 1. 定位

归一量化有两层：

| 平面 | 职责 | 文档 |
|------|------|------|
| 业务平面 | 数据、回测、信号、Web、风控 | [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) |
| 工作站控制平面 | TASK、审批、调度、锁、结果包 | 本文 |

居家（L0/L1）与远程（L2）是**两个入口**，收敛到同一套 TASK 协议与 `.ai/results/<TASK_ID>/`。远程入口迁移为 WorkBuddy Unified V3；CodeBuddy 保留 compatibility-only 回退。

V3 正式采用 GitHub Native Control Plane：GitHub `main` canonical docs 是项目事实源，task branch 中的 TASK 是执行契约，Issue 是生命周期，Draft PR / PR 是交付容器，`.ai/results/<TASK_ID>/` 是 local-first 执行证据。详见 [`GITHUB_NATIVE_CONTROL_PLANE.md`](GITHUB_NATIVE_CONTROL_PLANE.md) 与 [`ADR-WS-001`](../decisions/ADR-WS-001-github-native-control-plane.md)。

## 2. 事实源

| 层级 | 路径 / 平台 | 角色 |
|------|------|------|
| 项目事实 | GitHub `main` canonical docs | 长期目标、状态、边界、架构决策 |
| 执行契约 | task branch `docs/tasks/<TASK_ID>.md`（fallback `.ai/tasks/`） | dispatcher 和 Codex 的正式输入；Issue 不取代 TASK |
| 生命周期 | GitHub Issue | 状态、讨论、远程入口、脱敏摘要 |
| 变更交付 | Draft PR / PR | diff、CI、review、交付讨论；不自动 merge |
| 本地证据 | `.ai/results/<TASK_ID>/` | 路由、Plan、Review、Result Bundle、阶段日志 |
| 审批凭证 | `.ai/approvals/<TASK_ID>.json` | Plan SHA256 绑定的审批凭证 |
| Writer lock | `.ai/locks/worktrees/` | worktree writer lock（运行时，不提交 Git） |
| 当前指针 | `tasks/current.md` | 全局当前任务指针（非单个 TASK 细节源） |
| 非事实源 | WorkBuddy 对话 / memory | 只能辅助 intake 和交付，不得成为状态源 |

## 3. 组件

| 组件 | 脚本 | 职责 |
|------|------|------|
| Dispatcher | `scripts/ai/dispatch_task.sh` | 统一 stage 入口；环境 Gate、审批 Gate、writer lock |
| WorkBuddy facade | `scripts/ai/workbuddy_task.sh` | WorkBuddy 白名单入口；只调用既有受控脚本；不自由 shell、不裸调 Codex、不维护第二状态 |
| Router | `scripts/ai/route_task.sh` → `lib/route_task.py` | 解析 TASK 元信息、profile、sandbox、command |
| Writer lock | `scripts/ai/writer_lock.sh` | 同一 worktree 单 writer（codex / cursor / codebuddy） |
| Env check | `scripts/env/check_task_env.sh` | Required Env / Mounts / branch / worktree fail-closed |
| Plan | `scripts/ai/codex_plan.sh` | 只读 Plan（由 dispatch `plan` 调用） |
| Dev | `scripts/ai/codex_dev.sh` | workspace-write 开发（由 dispatch `dev`/`fix` 调用） |
| Test | `scripts/ai/run_tests.sh` | TASK §18.0 自动化测试 |
| Review | `scripts/ai/codex_review.sh` | 只读 Codex review |
| Result | `scripts/ai/collect_result.sh` | 结构化 Result Bundle + execution summary |
| Approval | `scripts/ai/approve_task.sh` | 用户批准后写入审批 JSON（含 `--confirm-production-write`） |
| Doctor | `scripts/ai/workstation_doctor.sh` | 聚合自检（profile、router、F02、env）；见 [`WORKSTATION_SELF_CHECK.md`](WORKSTATION_SELF_CHECK.md) |
| Control | `lib/dispatch_control.py` | pause / resume / cancel / status |

## 4. Stage × Sandbox × Lock 矩阵

| Stage | 调用模型 | Sandbox | 审批 | Writer lock | 子命令 |
|-------|----------|---------|------|-------------|--------|
| `route` | 否 | none | 否 | 否 | — |
| `plan` | 是 | read-only | 否 | 冲突检测 | `codex_plan.sh` |
| `dev` | 是 | workspace-write | 是 | 获取 codex | `codex_dev.sh` |
| `fix` | 是 | workspace-write | 是 | 获取 codex | `codex_dev.sh` |
| `test` | 否 | none | 否 | 否 | `run_tests.sh` |
| `review` | 是 | read-only | 否 | 冲突检测 | `codex_review.sh` |
| `result` | 否 | none | 否 | 否 | `collect_result.sh` |
| `pause` / `resume` / `cancel` / `status` | 否 | none | resume 时校验 | pause/cancel 释放 lock | `dispatch_control.py` |

Profile 详情见 [`ROUTING_POLICY.md`](ROUTING_POLICY.md)。Writer lock 交接见 [`WRITER_LOCK_HANDOFF.md`](WRITER_LOCK_HANDOFF.md)。

## 5. 双入口收敛

```text
Home (L0/L1)                         Remote (L2)
GPT + GitHub / Cursor           →    WorkBuddy PM/QA
Issue / task branch / Draft PR       WorkBuddy receives Issue #N / TASK_ID / PR #N
       ↓                                      ↓
init or bootstrap worktree             init or bootstrap worktree
       ↓                                      ↓
dispatch_task.sh *                     workbuddy_task.sh -> dispatch_task.sh *
       ↓                                      ↓
.ai/results/<TASK_ID>/                 .ai/results/<TASK_ID>/
       ↓                                      ↓
PR / 用户 / Cursor 验收                WorkBuddy 交付报告 -> 用户 merge
```

`*` 同一 dispatcher，同一 stage gate，同一结果目录。

WorkBuddy Unified V3 只做远程协调、PM、QA、视觉验收和交付摘要。核心代码仍由 Codex 执行，writer lock 仍使用 `codex`，不新增 `workbuddy` writer。Copilot 只用于明确 R3/L1、单模块、最多 5 文件的小修改。CodeBuddy 为 compatibility-only。

禁止任何 Agent 直接写 `main`、自动 merge、自动 deploy 或绕过 TASK / approval / scope / resource lock Gate。用户保留 Plan、生产写入、merge 和 deploy 的最终批准权。

## 6. 相关文档

- 居家流程：[`HOME_DEVELOPMENT.md`](HOME_DEVELOPMENT.md)
- 远程流程：[`REMOTE_DEVELOPMENT.md`](REMOTE_DEVELOPMENT.md)
- GitHub Native 控制平面：[`GITHUB_NATIVE_CONTROL_PLANE.md`](GITHUB_NATIVE_CONTROL_PLANE.md)
- WorkBuddy Unified V3：[`WORKBUDDY_UNIFIED_V3.md`](WORKBUDDY_UNIFIED_V3.md)
- WorkBuddy 命令协议：[`WORKBUDDY_COMMAND_PROTOCOL.md`](WORKBUDDY_COMMAND_PROTOCOL.md)
- WorkBuddy 安全边界：[`WORKBUDDY_SECURITY_BOUNDARY.md`](WORKBUDDY_SECURITY_BOUNDARY.md)
- V3 基线：[`GITHUB_NATIVE_V3_BASELINE.md`](GITHUB_NATIVE_V3_BASELINE.md)
- ADR：[`ADR-WS-001`](../decisions/ADR-WS-001-github-native-control-plane.md)
- 模型路由：[`ROUTING_POLICY.md`](ROUTING_POLICY.md)
- 环境 fail-closed：[`ENVIRONMENT_FAIL_CLOSED.md`](ENVIRONMENT_FAIL_CLOSED.md)
- 工作级别：[`docs/workflows/work_levels.md`](../workflows/work_levels.md)
- 交付 SOP：[`docs/workflows/ai_delivery_workflow.md`](../workflows/ai_delivery_workflow.md)
- 故障处理：[`docs/workflows/dispatcher_fault_handling.md`](../workflows/dispatcher_fault_handling.md)
