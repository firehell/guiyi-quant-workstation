# WS-V2-001: 现有工作站只读盘点

> 审计时间：2026-07-13 | 基线：main @ b50e8f31 | 仓库：guiyi-quant-workstation
> 范围：只读，不修改代码/配置/数据库/数据文件
> 输出：能力清单 / 可复用项 / 缺失项 / 兼容项 / 建议新增 / 依赖建议

---

## 目录

1. [当前能力清单](#1-当前能力清单)
2. [可直接复用项](#2-可直接复用项)
3. [缺失项](#3-缺失项)
4. [有缺陷但不能直接替换的兼容项](#4-有缺陷但不能直接替换的兼容项)
5. [Gate 体系回答](#5-gate-体系回答)
6. [建议新增/修改文件](#6-建议新增修改文件)
7. [WS-V2-002 至 WS-V2-009 的依赖建议](#7-ws-v2-002-至-ws-v2-009-的依赖建议)

---

## 1. 当前能力清单

### 1.1 脚本体系总览（29 脚本）

**scripts/ai/ 核心脚本（21 个）**

| 脚本 | 状态 | 说明 |
|------|------|------|
| `dispatch_task.sh` | ✅ 成熟 | 统一调度入口：route/plan/dev/fix/test/review/result + pause/resume/cancel/status |
| `route_task.sh` | ✅ 成熟 | 路由解析：提取 task_id/status/work_level/branch，推断 routing_tier（fast/standard/deep/critical） |
| `codex_plan.sh` | ✅ 成熟 | Plan 阶段：codex exec -s read-only，输出 .ai/results/<TASK_ID>/plan_result.md |
| `codex_dev.sh` | ✅ 成熟 | Dev 阶段：Issue/Branch/Approval Gate → codex exec -s workspace-write → Scope/HEAD Gate → run_tests |
| `codex_review.sh` | ✅ 成熟 | Review 阶段：只读 codex 审查 uncommitted/base/commit diff，含 Read-only Gate |
| `run_tests.sh` | ✅ 成熟 | 测试阶段：解析 TASK §18.0 fenced bash block，含安全命令白名单 + 敏感信息过滤 |
| `collect_result.sh` | ✅ 成熟 | Result 阶段：完整的 result_bundle.json + execution.json + execution_summary.md |
| `approve_task.sh` | ✅ 成熟 | 审批：Issue/Branch/Worktree Gate → generate_approval → verify_approval |
| `init_task_worktree.sh` | ✅ 成熟 | Worktree 初始化：自动创建分支/目录，回填 TASK Worktree/Branch 元信息 |
| `writer_lock.sh` | ✅ 成熟 | 资源锁 CLI 入口：acquire/release/break-stale/status |
| `workstation_doctor.sh` | ✅ 成熟 | 诊断：13 项 preflight 检查（git/codex/python/router/dispatcher/lock/env/writable 等） |
| `upgrade_task_level.sh` | ✅ 可用 | L1→L2 升级：验证 Issue #N + Worktree 已设 |
| `handoff_summary.sh` | ✅ 可用 | 交接摘要：git status + last commit + worktree list |
| `make_delivery_summary.sh` | ✅ 可用 | 交付摘要：从 result_bundle.json 生成 delivery_report_draft.md |
| `create_issue_from_task.sh` | ✅ 可用 | 从 TASK 创建 GitHub Issue |
| `link_task_issue.sh` | ✅ 可用 | 将 Issue #N 写入 TASK §0 元信息 |
| `comment_issue_result.sh` | ✅ 可用 | 将 plan/test/delivery 结果作为 Issue 评论 |
| `update_issue_status.sh` | ✅ 可用 | 同步 GitHub Issue status/* labels |
| `list_worktrees.sh` | ✅ 可用 | 列出所有 git worktree |
| `remove_task_worktree.sh` | ✅ 可用 | 清理已完成任务的 worktree |
| `run_v12_post_auth_e2e.sh` | ⚠️ 未验证 | V1.2 端到端验收脚本（状态未知） |

**存根脚本（5 个）**

| 脚本 | 状态 | 实际映射 |
|------|------|---------|
| `codexplan.sh` | 🔧 存根 | → dispatch_task.sh <ID> plan |
| `codexdev.sh` | 🔧 存根 | → dispatch_task.sh <ID> dev |
| `runtests.sh` | 🔧 存根 | → dispatch_task.sh <ID> test |
| `collectresult.sh` | 🔧 存根 | → dispatch_task.sh <ID> result |
| `makedeliverysummary.sh` | 🔧 存根 | → make_delivery_summary.sh --task <ID> |

**scripts/ai/lib/ Python 库（4 个）**

| 文件 | 状态 | 能力 |
|------|------|------|
| `task_meta.py` | ✅ 成熟 | TASK 解析：resolve + parse 21 字段模板 → TaskMeta dataclass |
| `route_task.py` | ✅ 成熟 | 路由：routing_tier 推断（fast/standard/deep/critical）+ 模型/沙箱选择 |
| `writer_lock.py` | ✅ 成熟 | 资源锁：acquire/release/break-stale/status，worktree-scoped，stale 检测 |
| `dispatch_control.py` | ✅ 成熟 | 控制阶段：pause/resume/cancel/status，状态持久化 |

### 1.2 Gate 体系（9 层）

| Gate | 位置 | 类型 | 描述 |
|------|------|------|------|
| **Issue Gate** | `_work_level_lib.sh` L77 | 强制（L2）/ 可选（L1）/ 跳过（L0） | `^#[0-9]+$` 正则，L2 缺失阻断 |
| **Branch Gate** | `_approve_lib.sh` L13 | 强制 | 禁止 main/master/detached HEAD + 需匹配 TASK Branch 字段 |
| **Worktree Gate** | `_work_level_lib.sh` L105 | 强制（L1/L2） | 当前 git toplevel 必须匹配 TASK Worktree 路径 |
| **Approval Gate** | `_approve_lib.sh` L61 | 强制（dev/fix） | 验证 .ai/approvals/<ID>.json：schema_version/task_id/task_file/branch/plan_sha256 |
| **Stage Gate** | `dispatch_task.sh` L245 | 强制 | 状态机验证（plan→APPROVED_DEV→dev, 等） |
| **Scope Gate** | `codex_dev.sh` L36 | 强制 | 变更文件必须在 TASK §7 allowed_paths 内，禁止在 forbidden_paths 内 |
| **HEAD Gate** | `codex_dev.sh` L35 | 强制 | codex 执行期间 HEAD 不可变 |
| **Read-only Gate** | `codex_review.sh` L190 | 强制 | review 期间 git diff 不可变 |
| **Production Write Gate** | `dispatch_task.sh` L304 | 条件 | 若 APP_ENV=production 需 production_write_approved=true |

### 1.3 状态机（12 状态）

```
IDEA → REQUIREMENT_READY → PLAN_READY → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → CLOSED
                                                                     ↓
                                                                  FAILED → REPLAN → PLAN_READY
                                                                     ↓
                                                                  IDEA / 丢弃

中断态：PAUSED ↔ resume / CANCELLED（不可 resume）
```

**10 正向状态**：IDEA / REQUIREMENT_READY / PLAN_READY / APPROVED_DEV / CODING / TESTING / DELIVERY_READY / CLOSED / FAILED / REPLAN
**2 中断态**：PAUSED / CANCELLED（V1.5 扩展）

### 1.4 工作级别（L0 / L1 / L2）

| 级别 | Issue Gate | Worktree | Branch | 用途 |
|------|-----------|----------|--------|------|
| L0 | 跳过 | 无要求 | main 可 | 纯文档/AI 工作流/调研 |
| L1 | 可选 | 独立 worktree | 非 main | 居家直控，Issue 可选 |
| L2 | 强制 `#N` | 独立 worktree | 非 main | 正式交付，Issue 必填 |

### 1.5 路由分级（fast / standard / deep / critical）

| Tier | 触发器 | 模型 profile | 示例任务类型 |
|------|--------|-------------|------------|
| fast | route/test/result 阶段 / L0 文档类 | 小模型 | 文档完善、测试 |
| standard | 默认 | 标准模型 | 常规开发 |
| deep | scheduler recovery/跨模块/runtime/恢复 关键词 | 大模型 | 复杂重构、多模块 |
| critical | 策略/回测/数据库/风控/EMA/MACD/seed | 最强模型 | 策略开发、数据链路 |

### 1.6 资源锁（Writer Lock）

- **范围**：worktree 级别（`.ai/locks/worktrees/<hash16>.json`）
- **写入者**：codex / cursor / codebuddy
- **操作**：acquire / release / break-stale / status
- **安全性**：
  - 同主机：PID 存活检查
  - 跨主机：启动时间 + `GUIYI_WRITER_LOCK_STALE_SECONDS`（默认 24h）
  - 审计：`.ai/locks/audit.jsonl`（每次 acquire/release/break-stale 记录）
- **自动获取**：dispatch_task.sh 在 dev/fix 阶段自动 acquire，plan/review 阶段检查冲突
- **自动释放**：trap EXIT/INT/TERM/HUP/QUIT

### 1.7 dry-run / apply 分离

| 方式 | 实现 |
|------|------|
| `--dry-run` 参数 | dispatch_task.sh 支持，只写 route.json 不执行 |
| `GUIYI_AI_DRY_RUN=1` | 环境变量全局 dry-run |
| `--explain` 参数 | 输出路由决策，不执行 |
| `route` 阶段 | 本身是 dry-run 性质的决策输出 |

### 1.8 诊断能力（workstation_doctor.sh）

13 项检查：git / codex / python3+uv+pnpm / task_parser / profile_templates / installed_profiles / router / dispatcher_dry_run / writer_lock / env_check / results_writable / f02_status_artifact / branch_not_main / no_credential_output

### 1.9 证据脱敏

| 位置 | 机制 |
|------|------|
| `run_tests.sh` | `sed -E 's/(QYWX_WEBHOOK\|token\|...)=.*/\1=[REDACTED]/I'` |
| `collect_result.sh` | `redact()` 函数：`\b(token\|webhook\|password\|secret\|...)` = [REDACTED] |
| `codex_review.sh` | 同样的 sed 脱敏模式 |
| 审批记录 | pre_existing_sha256 记录但内容脱敏 |

### 1.10 文档配置体系

| 文件 | 状态 | 内容 |
|------|------|------|
| `AGENTS.md` | ✅ 完整 | 项目定位/技术栈/风控/AI 工作站执行规则/Codex 规则 |
| `CODEBUDDY.md` | ✅ 完整 | CodeBuddy 角色/硬规则/七命令协议/标准执行序列/Stage Gate/Failure Handling |
| `docs/workflows/status_machine.md` | ✅ 完整 | 12 状态定义/进出条件/脚本映射 |
| `docs/workflows/ai_delivery_workflow.md` | ✅ 完整 | 半自动交付 SOP |
| `docs/workflows/work_levels.md` | ✅ 存在 | L0/L1/L2 定义 |
| `docs/workflows/github_issue_trace_workflow.md` | ✅ 存在 | GitHub Issue 追踪流程 |
| `docs/workflows/dispatcher_fault_handling.md` | ✅ 存在 | 故障处理 |
| `.github/workflows/workstation-test.yml` | ✅ 存在 | CI：workstation_doctor + bash -n + 4 profile 模板验证 |

---

## 2. 可直接复用项

| 序号 | 能力 | 复用方式 | 备注 |
|------|------|---------|------|
| R1 | dispatch_task.sh 调度器 | 直接调用 | 统一入口，9 个阶段 |
| R2 | _approve_lib.sh 审批库 | 直接 source | extract_task_field / check_branch / generate_approval / verify_approval / detect_plan_change |
| R3 | _work_level_lib.sh 工作级别库 | 直接 source | extract_work_level / check_issue_gate / check_worktree_gate / resolve_task_file |
| R4 | writer_lock.py 资源锁 | 直接 import | acquire/release/break-stale/status + 审计日志 |
| R5 | task_meta.py TASK 解析器 | 直接 import | resolve_task_file / parse_task_file → TaskMeta |
| R6 | route_task.py 路由器 | 直接 import | routing_tier 推断 + 模型/沙箱选择 |
| R7 | dispatch_control.py 控制阶段 | 直接 import | pause/resume/cancel/status |
| R8 | codex_plan.sh Plan 生成 | 直接调用 | 生成 .ai/results/<ID>/plan_result.md |
| R9 | codex_dev.sh Dev 执行 | 直接调用 | 完整 Gate 链 |
| R10 | run_tests.sh 测试执行 | 直接调用 | 安全命令白名单 + 脱敏 |
| R11 | collect_result.sh Result 打包 | 直接调用 | result_bundle.json + execution.json |
| R12 | workstation_doctor.sh 诊断 | 直接调用 | 13 项检查 |
| R13 | GitHub Issue 追踪链 | 直接调用 | create→link→comment→update_status |
| R14 | Worktree 初始化链 | 直接调用 | init→list→remove |
| R15 | 任务单 21 字段模板 | 直接使用 | §0 元信息 + 20 节 |
| R16 | 12 状态状态机 | 直接使用 | 已文档化 + dispatch_control.py 实现中断态 |

---

## 3. 缺失项

### 3.1 高优先级缺失

| 编号 | 缺失项 | 影响 | 建议 |
|------|--------|------|------|
| M1 | **R0/R1/R2/R3 风险分级** | 当前 routing_tier（fast/standard/deep/critical）是"复杂度"分级，不是"风险"分级。安全审计需要独立的 R0–R3 风险分级 | 新增 R0-R3 Risk Level 字段到 TASK §0，与 routing_tier 并行 |
| M2 | **自动化回滚** | 失败后回滚需人工执行 git revert。无自动回滚脚本 | 创建 `scripts/ai/revert_task.sh`，基于 approval 的 pre_existing_changes |
| M3 | **证据链完整性校验** | `collect_result.sh` 依赖各阶段的日志文件存在，但不验证缺失状态 | 新增 `verify_evidence_chain.sh` 检查 dev.log / test.log / review.md 完整性 |
| M4 | **跨 worktree 锁可见性** | `writer_lock.sh status` 只能检查指定 worktree，不能扫描所有 active lock | 新增 `writer_lock.sh list` 子命令 |
| M5 | **长稳运行记录** | 无正式运行日志轮转/聚合/保留策略。`.ai/logs/` 目录未见结构化 | 新增 `.ai/logs/` 结构 + 日志轮转策略 |
| M6 | **Plan → Dev 的 dry-run 确认** | `dispatch_task.sh` 的 `--dry-run` 不输出将要执行的具体命令给用户审查 | 在 `--dry-run` 输出中增加 resolved 命令列表 |

### 3.2 中优先级缺失

| 编号 | 缺失项 | 影响 | 建议 |
|------|--------|------|------|
| M7 | **并发任务协调** | writer_lock 保护单个 worktree，但不处理跨任务依赖（A 完成后 B 才能开始） | 新增 `scripts/ai/check_dependencies.sh` 读 TASK §21 依赖字段 |
| M8 | **TASK 状态自动同步** | 状态流转后需手动更新 TASK Status 字段（`set_task_meta_field`），无原子性保证 | 新增 `update_task_status.sh` 统一入口 |
| M9 | **审批记录过期策略** | `approve_task.sh` 不检查 Plan 是否已过时（仅 verify_approval 在 dev 时检查） | 新增 `check_approval_freshness.sh` 在 approve 阶段检查 |
| M10 | **数据目录保护** | `data/` 目录无额外的文件系统级保护 | 考虑 `.gitignore` 增强 + read-only mount 建议 |
| M11 | **策略代码风控扫描** | 策略/回测类任务（critical tier）无独立的风控扫描步骤 | 在 critical tier 的 plan 和 review 阶段增加风控 checklist |

### 3.3 低优先级缺失

| 编号 | 缺失项 | 影响 | 建议 |
|------|--------|------|------|
| M12 | **多仓库支持** | 当前脚本假设单仓库（`git -C "$SCRIPT_DIR" rev-parse --show-toplevel`） | 长期考虑支持 monorepo 多子项目 |
| M13 | **Webhook 通知规范化** | run_tests.sh 硬编码脱敏 QYWX_WEBHOOK 但不规范通知格式 | 新增统一的通知抽象层 |
| M14 | **任务指标统计** | 无 lead time / cycle time / 失败率 等 DORA 指标 | 从 `.ai/logs/` 和 `.ai/results/` 提取 |

---

## 4. 有缺陷但不能直接替换的兼容项

| 编号 | 兼容项 | 缺陷 | 不能替换原因 | 建议 |
|------|--------|------|------------|------|
| C1 | `codex_dev.sh` ISSUE= 提取使用旧版 `_approve_lib.sh` 的 `extract_task_field`（无 issue gate 函数） | 与 `_work_level_lib.sh` 的 `check_issue_gate` 行为不一致（旧版不区分 L0/L1/L2） | `codex_dev.sh` 是 DEV 主入口，现有 40+ 任务单依赖其行为 | 统一：`codex_dev.sh` 改用 `check_issue_gate` |
| C2 | `run_tests.sh` 的 `is_safe_command` 白名单不包含 `make` / `docker` / `gh` | 安全但限制过多，有时合理命令被拒 | 白名单扩展需要逐个命令评估风险 | 在 TASK §18.0 文档中明确支持的命令列表 |
| C3 | `collect_result.sh` 依赖 `_work_level_lib.sh` 的 `extract_worktree_path` 函数，函数在 `_approve_lib.sh` 中不存在 | 两库函数名冲突风险（extract_task_field vs extract_task_meta_field） | 大量脚本 source 两个 lib，重命名风险高 | 文档化两个 lib 的函数清单，明确调用约定 |
| C4 | TASK 模板 21 字段：`## 0. 元信息` 与 `## 1. 任务状态` 之间存在字段冗余（Status 两次出现） | 不一致风险 | 46 个现有任务单依赖此结构 | 新增 TASK 模板版本字段，渐进迁移 |
| C5 | `codex_review.sh` 在 L1 时执行 check_worktree_gate | 对于 L1 任务，如果 worktree 未设置会触发 Gate 失败 | review 是只读操作，worktree gate 在此阶段可能过于严格 | 调整：review 阶段 L1 跳过 worktree gate |
| C6 | `dispatch_task.sh` 使用 bash 的 `json_get` 从 route_json 提取字段，无类型安全 | JSON 解析健壮性依赖 python3 子进程 | 重构为纯 Python 工作量过大 | 保持现状，增加 route.json schema 校验 |

---

## 5. Gate 体系回答

### 5.1 当前有哪些能力已经完成

✅ **完成矩阵**：

- [x] Issue Gate（L0/L1/L2 三级，正则 `^#[0-9]+$`）
- [x] Branch Gate（禁止 main/master + 匹配 TASK Branch 字段）
- [x] Worktree Gate（当前 worktree 路径匹配 TASK Worktree 字段）
- [x] Approval Gate（Plan SHA256 绑定验证）
- [x] Scope Gate（allowed_paths/forbidden_paths 基于 TASK §7）
- [x] HEAD Gate（codex 执行期间 HEAD 不变）
- [x] Read-only Gate（review 期间 diff 不变）
- [x] Stage Gate（dispatch 阶段状态机验证）
- [x] Production Write Gate（APP_ENV=production 需额外批准）
- [x] 12 状态状态机（含 PAUSED/CANCELLED 中断态）
- [x] dry-run/apply 分离（`--dry-run` + `GUIYI_AI_DRY_RUN=1`）
- [x] Writer Lock（worktree-scoped acquire/release/break-stale + audit）
- [x] 证据脱敏（run_tests/collect_result/codex_review 三级脱敏）
- [x] GitHub Issue 全链路追踪（create→link→comment→update_status）
- [x] Worktree 全生命周期管理（init→list→remove）
- [x] 诊断工具（workstation_doctor.sh 13 项检查）
- [x] CI 流水线（`.github/workflows/workstation-test.yml`）

### 5.2 哪些只是文档存在但脚本未执行

| 项目 | 文档引用 | 脚本状态 |
|------|---------|---------|
| `docs/workstation/HOME_DEVELOPMENT.md` | AGENTS.md §8.1 引用 | ⚠️ 文件缺失（worktree 中不存在） |
| `docs/workstation/REMOTE_DEVELOPMENT.md` | AGENTS.md / CODEBUDDY.md 引用 | ⚠️ 文件缺失（worktree 中不存在） |
| `docs/workstation/ENVIRONMENT_FAIL_CLOSED.md` | AGENTS.md §8.1 引用 | ⚠️ 文件缺失（worktree 中不存在） |
| `docs/workstation/WRITER_LOCK_HANDOFF.md` | AGENTS.md §8.1 引用 | ⚠️ 文件缺失（worktree 中不存在） |
| `docs/workstation/ROUTING_POLICY.md` | AGENTS.md / CODEBUDDY.md 引用 | ⚠️ 文件缺失（worktree 中不存在） |
| `run_v12_post_auth_e2e.sh` | 存在于 scripts/ai/ | ⚠️ 从未执行（无 .ai/results 记录） |
| `docs/AI_WECHAT_WORKFLOW.md` | CODEBUDDY.md 引用 | ⚠️ 文件缺失（worktree 中不存在） |

> **警告**：AGENTS.md 和 CODEBUDDY.md 引用了 7 个 `docs/workstation/` 下的文档，但这些文件在工作树中**全部缺失**。这是文档债务，可能导致新 Agent/新贡献者无法理解完整的执行规则。

### 5.3 哪些脚本会绕过审批

| 路径 | 风险 | 可能性 |
|------|------|--------|
| **直接调用 `codex_dev.sh`** | 绕过 `dispatch_task.sh` 的 Stage Gate 和 Production Write Gate | 🟡 中等 — 若有人绕过 CodeBuddy 直接执行 |
| **直接调用 `codex exec`** | 完全绕过所有 Gate | 🔴 高 — 仅靠开发者纪律 |
| **直接调用 `approve_task.sh`** | 审批记录生成不需要用户交互确认（脚本无 `read -p` 确认） | 🟢 低 — 依赖 CodeBuddy/WorkBuddy 的工作流纪律 |
| **修改 TASK §7 allowed_paths** | 可在审批后修改白名单扩大范围 | 🟡 中等 — Scope Gate 基于当前 TASK 内容，若 Plan 批准后修改 TASK 而 Plan SHA 不变，Scope Gate 可能放过 |

> **结论**：审批的核心防线是 `verify_approval` 中的 **Plan SHA256 绑定**。如果 Plan 不变、仅修改 TASK §7，则 `approve_task.sh` 会因 Task SHA256 变化而失败。但 `codex_dev.sh` 自己不做 TASK SHA 验证——它只验证 Approval JSON 中的字段。这是设计上的 Gap：**Approval 绑定了 TASK SHA256，但 codex_dev.sh 不验证当前 TASK 文件 SHA256 是否与审批时一致。**

### 5.4 是否支持 R0/R1/R2/R3

**不支持**。当前的分级体系是：

| 体系 | 用途 | 分级 |
|------|------|------|
| routing_tier | 模型/沙箱选择 | fast / standard / deep / critical |
| work_level | 流程纪律 | L0 / L1 / L2 |

这与 R0–R3 风险分级不同：
- R0 → 自动交易/密钥泄露/data loss → 当前无对应的自动阻断
- R1 → 策略/回测/数据库 → 部分映射到 `critical` routing_tier（但是"用更强模型"而非"增加审查步骤"）
- R2 → 一般代码变更 → 映射到 standard
- R3 → 纯文档 → 映射到 fast/L0

**需要新增独立的 R0–R3 Risk Level 字段**。

### 5.5 是否支持资源锁和恢复

**支持**：

| 能力 | 状态 | 详情 |
|------|------|------|
| 资源锁（Writer Lock） | ✅ | worktree-scoped，PID/stale 检测，自动 acquire/release |
| Lock 恢复（break-stale） | ✅ | `writer_lock.sh break-stale`，基于 pid 存活 + 时间阈值 |
| Lock 审计 | ✅ | `.ai/locks/audit.jsonl` 记录每次 acquire/release/break-stale |
| 任务恢复（Resume） | ✅ | `dispatch_task.sh <ID> resume` 恢复 PAUSED 任务 |
| 锁冲突保护 | ✅ | dispatch_task.sh 在 plan/review 阶段检查 writer 冲突 |
| **多 worktree 锁扫描** | ❌ | 缺少 `writer_lock.sh list` 子命令 |
| **跨任务依赖锁** | ❌ | 无 A→B 任务依赖的锁协调 |

### 5.6 是否兼容已有任务

**完全兼容**：

- ✅ 所有 46 个现有任务使用同一 21 字段模板（`## 0. 元信息` + 20 节）
- ✅ 现有任务的任务单路径约定（`docs/tasks/<ID>.md` → `.ai/tasks/<ID>.md` → `docs/tasks/examples/`）
- ✅ GUIYI-DEMO-001 已验证完整链路通过（IDEA→RESULT_READY）
- ✅ 现有 9 个 worktree 与 writer_lock 机制无冲突

---

## 6. 建议新增/修改文件

### 6.1 新增文件（高优先级）

| 文件 | 用途 | 依赖 |
|------|------|------|
| `scripts/ai/check_approval_freshness.sh` | Plan 审批通过后检查是否有新的变更使审批失效 | M9 |
| `scripts/ai/verify_evidence_chain.sh` | 验证 dev.log/test.log/review.md 完整性 | M3 |
| `scripts/ai/update_task_status.sh` | 统一 TASK Status 字段更新入口 | M8 |
| `scripts/ai/risk_gate.sh` | R0–R3 风险分级 Gate（阻断 R0/R1 未经额外审批） | M1 |
| `docs/workstation/RISK_LEVELS.md` | R0–R3 风险分级定义 | M1 |
| `docs/tasks/workstation/WS-V2-001-workstation-audit.md` | 本审计报告 | — |

### 6.2 新增文件（中优先级）

| 文件 | 用途 | 依赖 |
|------|------|------|
| `scripts/ai/check_dependencies.sh` | 跨任务依赖检查 | M7 |
| `scripts/ai/revert_task.sh` | 基于 approval pre_existing_changes 自动回滚 | M2 |
| `scripts/ai/scan_worktrees.sh` | 多 worktree 状态扫描（替代 writer_lock.sh list） | M4 |
| `docs/workstation/` 下缺失的 7 个文档 | 补全 AGENTS.md/CODEBUDDY.md 引用的文档 | 见 §5.2 |

### 6.3 修改文件

| 文件 | 修改内容 | 原因 |
|------|---------|------|
| `scripts/ai/codex_dev.sh` | ① ISSUE= 改用 `check_issue_gate` ② 增加 TASK SHA256 一致性检查 | C1 + TASK SHA Gap |
| `scripts/ai/run_tests.sh` | `is_safe_command` 白名单增加 `make` | C2 |
| `scripts/ai/codex_review.sh` | L1 时跳过 worktree gate | C5 |
| `TASK_TEMPLATE.md` | 新增 Risk Level (R0-R3) 字段，去重 Status 字段 | C4 + M1 |

---

## 7. WS-V2-002 至 WS-V2-009 的依赖建议

```
WS-V2-001 (本审计)
  │
  ├── WS-V2-002: 补全缺失文档
  │     └─ 依赖：无（纯文档任务，L0）
  │     └─ 产出：7 个 docs/workstation/ 文档
  │
  ├── WS-V2-003: 统一 Gate 入口 + TASK SHA 一致性
  │     └─ 依赖：WS-V2-001（审计发现 C1）
  │     └─ 产出：codex_dev.sh 重构 + check_issue_gate 统一
  │
  ├── WS-V2-004: 引入 R0–R3 风险分级
  │     └─ 依赖：WS-V2-001（审计发现 M1）
  │     └─ 产出：risk_gate.sh + RISK_LEVELS.md + TASK 模板更新
  │
  ├── WS-V2-005: 证据链完整性 + 任务状态同步
  │     └─ 依赖：WS-V2-003（统一 Gate 后）
  │     └─ 产出：verify_evidence_chain.sh + update_task_status.sh
  │
  ├── WS-V2-006: 资源锁增强（多 worktree 扫描 + 跨任务依赖）
  │     └─ 依赖：WS-V2-003（Gate 统一后）
  │     └─ 产出：scan_worktrees.sh + check_dependencies.sh
  │
  ├── WS-V2-007: 自动化回滚 + 审批过期策略
  │     └─ 依赖：WS-V2-005（证据链完整后）
  │     └─ 产出：revert_task.sh + check_approval_freshness.sh
  │
  ├── WS-V2-008: 长稳运行 + 日志聚合 + 指标统计
  │     └─ 依赖：WS-V2-005（证据链完整后）
  │     └─ 产出：日志轮转策略 + DORA 指标提取
  │
  └── WS-V2-009: Demo 验证 + 合并 main
        └─ 依赖：WS-V2-002 ~ 008 全部完成
        └─ 产出：通过 workstation_doctor.sh + 端到端 Demo 任务
```

**并行执行建议**：
- WS-V2-002 + WS-V2-003 可并行（文档与代码不冲突）
- WS-V2-004 可与 WS-V2-003 并行（独立新增，不修改现有 Gate）
- WS-V2-005 必须在 WS-V2-003 之后（依赖统一 Gate）
- WS-V2-006 / WS-V2-007 / WS-V2-008 可并行（独立模块）

---

## 附录：审计范围确认

- [x] docs/tasks / docs/workflows / tasks/current.md
- [x] .ai/tasks / .ai/results / .ai/approvals / .ai/locks（.ai/locks 不存在）
- [x] scripts/ai 下所有 plan/dev/test/review/result/dispatch/approve 脚本
- [x] AGENTS.md / CODEBUDDY.md 和相关执行规则
- [x] 状态机 / Plan SHA 校验 / 审批记录校验 / Branch Gate / Issue Gate / 脏工作区规则
- [x] worktree 环境初始化方式
- [x] 资源锁 / dry-run/apply 分离 / 长稳运行记录 / 证据脱敏

> 审计完成时间：2026-07-13T15:41:00Z | 未修改任何文件（本报告除外）
