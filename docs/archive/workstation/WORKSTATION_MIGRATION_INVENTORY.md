# Workstation Migration Inventory

更新时间：2026-07-16

任务：`WS-WB-V3-FINAL-001` / Commit B

本文记录本次实际落地动作。没有出现在本表的文件，本轮不删除；若扫描发现但未能确认关闭或替代，按 `REVIEW_REQUIRED` 留待后续任务。

## 动作枚举

| action | 含义 |
|---|---|
| KEEP_CANONICAL | 当前权威入口，保留 |
| UPDATE_CANONICAL | 当前权威入口，本轮同步角色或链接 |
| ARCHIVE_GIT_MV | 使用 `git mv` 归档为历史参考 |
| DELETE_GENERATED | 可复现生成物，使用 `git rm` 从仓库移除 |
| UNTRACK_RUNTIME | 本地运行产物，使用 `git rm --cached` 从索引移除 |
| KEEP_COMPATIBILITY | 仍被兼容脚本/测试读取，保留 |
| REVIEW_REQUIRED | 未获明确分类，本轮不移动、不删除 |

## Canonical / active 文件

| path | category | current_role | action | target_path | reason | references | risk |
|---|---|---|---|---|---|---|---|
| `AGENTS.md` | canonical | 全局 Agent / 工作站边界 | KEEP_CANONICAL | - | Commit A 已更新 WorkBuddy V3 角色 | root guide | 低 |
| `README.md` | canonical | 项目入口与导航 | KEEP_CANONICAL | - | Commit A 已补工作站 canonical 导航 | root navigation | 低 |
| `PROJECT_SOURCE.md` | canonical | 项目事实入口 | KEEP_CANONICAL | - | Commit A 已写 WorkBuddy 统一协调与 CodeBuddy 兼容 | project source | 低 |
| `STATUS.md` | canonical | 当前状态 | KEEP_CANONICAL | - | Commit A 已标记工作站升级中且不改业务 Gate | status source | 低 |
| `CODEBUDDY.md` | compatibility | CodeBuddy 旧入口说明 | KEEP_COMPATIBILITY | - | 顶部已声明 compatibility-only；旧任务仍可读 | WorkBuddy fallback | 中 |
| `docs/workstation/ARCHITECTURE.md` | canonical | 工作站架构 | UPDATE_CANONICAL | - | 移除 active baseline 链接，转向 document map | workstation docs | 低 |
| `docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md` | canonical | GitHub Native 控制平面 | UPDATE_CANONICAL | - | 移除 active baseline 链接，加入 WorkBuddy V3 / document map | workstation docs | 低 |
| `docs/workstation/WORKBUDDY_UNIFIED_V3.md` | canonical | WorkBuddy V3 角色权威说明 | KEEP_CANONICAL | - | Commit A 新增 | WorkBuddy V3 | 低 |
| `docs/workstation/WORKBUDDY_SECURITY_BOUNDARY.md` | canonical | WorkBuddy 安全边界 | KEEP_CANONICAL | - | Commit A 新增 | WorkBuddy V3 | 低 |
| `docs/workstation/WORKBUDDY_COMMAND_PROTOCOL.md` | canonical | WorkBuddy facade 命令协议 | KEEP_CANONICAL | - | Commit A 新增 | WorkBuddy V3 | 低 |
| `docs/workstation/HOME_DEVELOPMENT.md` | canonical | 居家直连 dispatcher | KEEP_CANONICAL | - | Commit A 已保持直接 dispatcher | workflow | 低 |
| `docs/workstation/REMOTE_DEVELOPMENT.md` | canonical | 远程 WorkBuddy 入口 | KEEP_CANONICAL | - | Commit A 已切换到 `workbuddy_task.sh` | workflow | 低 |
| `docs/AGENT_WORKFLOW.md` | canonical | Agent 协作流程 | KEEP_CANONICAL | - | Commit A 已更新 GPT 可直接读 GitHub | workflow | 低 |
| `docs/AI_WECHAT_WORKFLOW.md` | canonical | 企业微信/远程协作流程 | UPDATE_CANONICAL | - | 修正 GPT 同步清单，不再 active 链接旧 baseline | workflow | 低 |
| `docs/tasks/TASK_TEMPLATE.md` | canonical | TASK 模板 | UPDATE_CANONICAL | - | 移除旧 `STATE_MACHINE_TICKET` / `TASK_MATRIX` active 假设 | task contract | 中 |
| `scripts/ai/workbuddy_task.sh` | canonical | WorkBuddy 白名单 facade | KEEP_CANONICAL | - | Commit A 新增 | command boundary | 中 |
| `.agents/skills/guiyi-workstation-orchestrator/` | canonical | WorkBuddy 主 skill | KEEP_CANONICAL | - | Commit A 新增 | skill boundary | 中 |
| `.agents/skills/guiyi-delivery-team/SKILL.md` | canonical | 专家交付团队 skill | KEEP_CANONICAL | - | Commit A 已去除 CodeBuddy 必经假设 | delivery | 低 |
| `prompts/workbuddy-*.md` | canonical | WorkBuddy prompt 套件 | KEEP_CANONICAL | - | Commit A 新增/更新 | prompts | 低 |
| `scripts/ai/run_v12_post_auth_e2e.sh` | compatibility wrapper | V1.2 Post-Auth E2E 兼容脚本 | KEEP_COMPATIBILITY | - | 仍被旧验收和 WS-V2 audit 引用；未满足删除条件 | `git grep` | 中 |
| `scripts/ai/upgrade_task_level.sh` | compatibility wrapper | L1→L2 升级脚本 | KEEP_COMPATIBILITY | - | 仍被 `docs/workflows/work_levels.md` 和 tests/任务引用 | `git grep` | 中 |
| `scripts/ai/audit_github_task_links.py` | compatibility helper | GitHub TASK migration 审计脚本 | UPDATE_CANONICAL | - | 默认 doc report 改为 ignored generated output，避免重建 active report | tests pass | 中 |

## 使用 `git mv` 归档的历史工作站文档

| source | action | target_path | reason | references | risk |
|---|---|---|---|---|---|
| `workstation/BASELINE_FREEZE.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/workstation-root/BASELINE_FREEZE.md` | 已被 WorkBuddy V3 canonical 替代；无运行时读取 | historical references only | 低 |
| `workstation/STATION_CONFIG.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/workstation-root/STATION_CONFIG.md` | 早期 Final v1.0 配置，当前入口改为 `docs/workstation/*` | historical references only | 低 |
| `workstation/team/COLLAB_PROTOCOL.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/COLLAB_PROTOCOL.md` | 旧 WorkBuddy/CodeBuddy/Codex 三方协议 | archive internal refs | 低 |
| `workstation/team/DAILY_COMMANDS.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/DAILY_COMMANDS.md` | 旧日常命令手册，已由 facade 协议替代 | archive internal refs | 低 |
| `workstation/team/MACMINI_OPS_MANUAL.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/MACMINI_OPS_MANUAL.md` | 旧 Mac mini 运行手册，当前远程/居家流程已分拆 | archive internal refs | 低 |
| `workstation/team/ROLE_SPEC.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/ROLE_SPEC.md` | 旧 12 角色定义，当前改为最少必要专家 | archive internal refs | 低 |
| `workstation/team/SECURITY_HANDBOOK.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/SECURITY_HANDBOOK.md` | 安全原则已迁入 AGENTS / WorkBuddy security boundary | archive internal refs | 低 |
| `workstation/team/STATE_MACHINE_TICKET.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/STATE_MACHINE_TICKET.md` | 旧独立状态机不再 active | archive internal refs | 中 |
| `workstation/team/TASK_MATRIX.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/TASK_MATRIX.md` | 旧任务矩阵不再 active | archive internal refs | 中 |
| `workstation/team/TEST_EXPERT_HANDBOOK.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/TEST_EXPERT_HANDBOOK.md` | QA 角色能力保留在 delivery skill / WorkBuddy prompts | archive internal refs | 低 |
| `workstation/team/UX_VISUAL_SPEC.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/team/UX_VISUAL_SPEC.md` | 历史视觉规范保留供旧前端任务追溯 | archive internal refs | 低 |

## 使用 `git mv` 归档的历史 TASK / 验收样例

| source | action | target_path | reason | references | risk |
|---|---|---|---|---|---|
| `tasks/TASK-2026-07-09-001-workstation-scaffold.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/TASK-2026-07-09-001-workstation-scaffold.md` | 早期工作站 scaffold 任务，已关闭历史 | archive only | 低 |
| `tasks/TASK-2026-07-09-002-readme-workstation-sync.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/TASK-2026-07-09-002-readme-workstation-sync.md` | 早期 README 同步任务，已被当前 README/WorkBuddy V3 替代 | archive only | 低 |
| `tasks/TASK-2026-07-10-001-workstation-v1.2.1-closeout.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/TASK-2026-07-10-001-workstation-v1.2.1-closeout.md` | V1.2.1 closeout 历史任务 | archive only | 低 |
| `tasks/TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/TASK-2026-07-10-002-workstation-v1.3-codebuddy-daemon.md` | CodeBuddy daemon 历史任务，当前 CodeBuddy compatibility-only | archive only | 低 |
| `docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/TASK-2026-07-10-003-workstation-lean-v1-closeout.md` | Lean V1 历史任务 | archive only | 低 |
| `docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/TASK-2026-07-11-001-workstation-lean-v1-closeout.md` | Lean V1 closeout 历史任务 | archive only | 低 |
| `docs/tasks/TASK-2026-07-11-002-lean-v1-demo.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/TASK-2026-07-11-002-lean-v1-demo.md` | Lean V1 Demo 历史任务 | archive only | 低 |
| `docs/tasks/GUIYI-DEMO-001.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/GUIYI-DEMO-001.md` | 早期 Demo 任务，运行产物已 untrack | compat reader docstring updated | 低 |
| `docs/tasks/examples/V1.1-ACCEPTANCE.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/V1.1-ACCEPTANCE.md` | V1.1 验收历史 | archive only | 低 |
| `docs/tasks/examples/V1.2-ACCEPTANCE.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/V1.2-ACCEPTANCE.md` | V1.2 验收历史 | archive only | 低 |
| `docs/tasks/examples/V1.5-ACCEPTANCE.md` | ARCHIVE_GIT_MV | `docs/tasks/archive/workstation-legacy/V1.5-ACCEPTANCE.md` | V1.5 验收历史 | active references updated to archive | 中 |

## 使用 `git mv` 归档的报告 / Demo

| source | action | target_path | reason | references | risk |
|---|---|---|---|---|---|
| `docs/workflows/LEAN_WORKFLOW_DEMO.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/demos/LEAN_WORKFLOW_DEMO.md` | Lean V1 Demo 记录，非当前 SOP | archive only | 低 |
| `docs/workstation/GITHUB_NATIVE_V3_BASELINE.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/reports/GITHUB_NATIVE_V3_BASELINE.md` | 历史基线，当前入口为 control plane + WorkBuddy V3 | active links replaced | 中 |
| `docs/workstation/GITHUB_TASK_MIGRATION_REPORT.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/reports/GITHUB_TASK_MIGRATION_REPORT.md` | 一次性迁移报告，后续脚本输出到 ignored outputs | script default updated | 中 |
| `docs/gpt/WORKSTATION_ROUTER_V1_AUDIT.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/reports/WORKSTATION_ROUTER_V1_AUDIT.md` | 旧 router V1 审查包 | self-reference only | 低 |
| `outputs/workstation-github-migration/migration_report.md` | ARCHIVE_GIT_MV | `docs/workstation/archive/pre-workbuddy-v3/reports/workstation-github-migration-report.md` | human-readable migration report 保留历史价值 | generated output moved | 低 |

## 删除 / 取消追踪的生成物和运行产物

| path | action | target_path | reason | references | risk |
|---|---|---|---|---|---|
| `outputs/workstation-github-migration/migration_matrix.csv` | DELETE_GENERATED | - | `audit_github_task_links.py` 可复现生成 | script output | 低 |
| `outputs/workstation-github-migration/migration_matrix.json` | DELETE_GENERATED | - | `audit_github_task_links.py` 可复现生成 | script output | 低 |
| `.ai/approvals/**` | UNTRACK_RUNTIME | - | 本地审批凭证，不能作为 Git 事实源 | `.gitignore` | 中 |
| `.ai/results/**` | UNTRACK_RUNTIME | - | 本地执行证据，local-first，不提交长日志/敏感上下文 | `.gitignore` | 中 |
| `.ai/runtime-gates/**` | UNTRACK_RUNTIME | - | 本地 runtime gate ledger | `.gitignore` | 中 |
| `.ai/task-runtime/**` | UNTRACK_RUNTIME | - | 本地 runtime overlay | `.gitignore` | 中 |
| `.ai/tasks/**` | UNTRACK_RUNTIME | - | 本地临时任务文件；正式 TASK 应进入 `docs/tasks/<TASK_ID>.md` | `.gitignore` | 中 |
| `.workbuddy/memory/**` | UNTRACK_RUNTIME | - | WorkBuddy memory 不是状态源 | `.gitignore` | 中 |

保留追踪：

- `.ai/schema/task.schema.json`

## 本轮未移动 / 未删除的 REVIEW_REQUIRED 类

| path | category | current_role | action | target_path | reason | references | risk |
|---|---|---|---|---|---|---|---|
| `docs/tasks/workstation/WS-V2-*.md` | workstation planning tasks | WS-V2 规划任务 | REVIEW_REQUIRED | - | Step 3 未逐文件明确关闭，且可能仍用于后续 V2/V3 对照 | docs/tasks/workstation | 中 |
| `docs/tasks/examples/TASK-*.md` | examples | fixture / historical examples | REVIEW_REQUIRED | - | 未在 Step 3 明确列入；测试可能引用 examples | tests / docs | 中 |
| `docs/tasks/examples/V1.4-ACCEPTANCE.md` | acceptance example | V1.4 验收样例 | REVIEW_REQUIRED | - | 未在 Step 3 明确列入 | docs/tasks/examples | 中 |
| `docs/workstation/demos/*.md` | demos | GitHub Native V3 demo docs | REVIEW_REQUIRED | - | 仍可能服务 Step 5/6 E2E demo | docs/workstation/demos | 中 |
