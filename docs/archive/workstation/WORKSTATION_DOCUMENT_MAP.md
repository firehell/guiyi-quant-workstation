# Workstation Document Map

更新时间：2026-07-16

本文是工作站文档导航，不替代各 canonical 文件内容。

## 当前权威入口

| 主题 | 当前文件 |
|---|---|
| 全局 Agent 边界 | `AGENTS.md` |
| 项目入口 | `README.md` |
| 项目事实源 | `PROJECT_SOURCE.md` |
| 当前状态 | `STATUS.md` |
| 工作站架构 | `docs/workstation/ARCHITECTURE.md` |
| GitHub Native 控制平面 | `docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md` |
| WorkBuddy Unified V3 | `docs/workstation/WORKBUDDY_UNIFIED_V3.md` |
| WorkBuddy 安全边界 | `docs/workstation/WORKBUDDY_SECURITY_BOUNDARY.md` |
| WorkBuddy 命令协议 | `docs/workstation/WORKBUDDY_COMMAND_PROTOCOL.md` |
| 居家开发 | `docs/workstation/HOME_DEVELOPMENT.md` |
| 远程开发 | `docs/workstation/REMOTE_DEVELOPMENT.md` |
| 路由策略 | `docs/workstation/ROUTING_POLICY.md` |
| TASK Schema | `docs/workstation/TASK_SCHEMA_V2.md` |
| TASK 模板 | `docs/tasks/TASK_TEMPLATE.md` |
| WorkBuddy 主 skill | `.agents/skills/guiyi-workstation-orchestrator/SKILL.md` |
| WorkBuddy facade | `scripts/ai/workbuddy_task.sh` |

## 兼容保留

| 文件 | 角色 |
|---|---|
| `CODEBUDDY.md` | compatibility-only 旧入口说明；不新增功能 |
| `prompts/codebuddy-execution.md` | 旧 CodeBuddy prompt；仅旧任务回读 |
| `scripts/ai/run_v12_post_auth_e2e.sh` | V1.2 Post-Auth E2E 兼容脚本 |
| `scripts/ai/upgrade_task_level.sh` | L1→L2 升级兼容脚本 |
| `scripts/ai/audit_github_task_links.py` | GitHub TASK migration 审计 helper；输出目录为 ignored generated output |

## 历史归档

| 目录 | 内容 |
|---|---|
| `docs/workstation/archive/pre-workbuddy-v3/workstation-root/` | 早期 `workstation/` 根目录文档 |
| `docs/workstation/archive/pre-workbuddy-v3/team/` | 早期 12 角色、任务矩阵、独立状态机、日常命令手册 |
| `docs/workstation/archive/pre-workbuddy-v3/reports/` | GitHub Native V3 baseline、migration report、router audit 等旧审查包 |
| `docs/workstation/archive/pre-workbuddy-v3/demos/` | Lean V1 demo 等历史演示记录 |
| `docs/tasks/archive/workstation-legacy/` | V1.1/V1.2/V1.5/Lean/CodeBuddy daemon 等旧 TASK 与验收记录 |

归档内容只供追溯，不再作为当前执行规则。若 archive 文档与 canonical 冲突，以 canonical 为准。

## 不进入 Git 的本地运行内容

| 路径 | 处理 |
|---|---|
| `.ai/approvals/**` | local-only，审批凭证不提交 |
| `.ai/results/**` | local-first，结果摘要回填 Issue/PR，不提交长日志 |
| `.ai/runtime-gates/**` | local-only runtime ledger |
| `.ai/task-runtime/**` | local-only runtime overlay |
| `.ai/tasks/**` | local-only 临时任务；正式 TASK 使用 `docs/tasks/<TASK_ID>.md` |
| `.workbuddy/memory/**` | WorkBuddy memory 不是状态源，不提交 |
| `outputs/workstation-github-migration/**` | 可复现 migration audit 输出，不提交 |
