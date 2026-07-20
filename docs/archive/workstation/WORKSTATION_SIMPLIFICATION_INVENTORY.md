# Workstation Simplification Inventory

| Field | Value |
|---|---|
| Task ID | `WS-SIMPLIFY-00-BASELINE-INVENTORY` |
| Branch | `codex/workstation-simplify` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/workstation-simplify` |
| Baseline commit | `964a961a` |
| Inventory date | 2026-07-20 |
| Mode | Read-only inventory; **no behavior change** |
| Prior mode | `WORKSTATION_NON_BLOCKING_SUPPORT_MODE`（已存在；本次是进一步精简，不是重建） |
| Target mode | `WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY` |

> **硬规则**：未发现调用 ≠ 可安全删除。任何删除必须以本表 + Step 5 Pilot 证据 + `git grep` / CI / runtime / deploy 复检为准。

相关历史（不替代本表）：[`WORKSTATION_MIGRATION_INVENTORY.md`](WORKSTATION_MIGRATION_INVENTORY.md)（2026-07-16，仍把 WorkBuddy 标为 KEEP_CANONICAL；本精简 inventory 覆盖其后续处置建议）。

---

## 0. Executive summary

当前控制面仍是完整的 **GitHub Native V3 + WorkBuddy facade + dispatcher stage 机 + 双 GPT 摘要包 + 多任务状态源**。业务已在 non-blocking support 模式，但文档与脚本表面积仍然过大。

| 面 | 现状 | 精简方向 |
|---|---|---|
| 工具模型 | GPT / WorkBuddy / CodeBuddy / Codex / Cursor / 企微 多入口 | GPT 浏览器 + GitHub + Codex + 用户；iPhone ChatGPT 仅 Codex 远程入口 |
| 状态源 | STATUS + CODEX_TASKS + tasks/current(1235 行) + Issue + docs/tasks + .ai + WorkBuddy memory | STATUS + Issue/PR + DECISIONS + 高风险 docs/tasks + 版本化证据 |
| 工程入口 | 仅有 `scripts/ai/**`（约 64 文件）+ `scripts/env/**`；**无** `scripts/engineering/**` | Step 4 提取真 Gate → `scripts/engineering/*`；Step 6 删旧控制面 |
| 文档 | `docs/workstation` 大量 active + 双份 project_sources | Step 1 收敛 canonical；Step 3 归档旧协议与 GPT 摘要 |

`git grep` 命中含 `WorkBuddy|CodeBuddy|dispatch_task|tasks/current|CODEX_TASKS` 的跟踪文件约 **205** 个（含历史 TASK / reports）。删除前必须按路径类分别复检。

---

## 1. Document inventory

### 1.1 Root canonical / entry

| Path | Duty today | Canonical? | Duplication | Referenced by README/AGENTS/PS | Disposition | Migrate to |
|---|---|---|---|---|---|---|
| `README.md` (123 行) | 项目入口与导航 | 入口 yes；事实段部分 stale | 与 STATUS 重复状态 | — | **compress** (Step 1) | 导航 → AGENTS + `docs/DEVELOPMENT.md` |
| `AGENTS.md` (754 行) | Agent 全局规则 + 完整工作站协议 | yes（过重） | 与 control plane / workflows 大量重叠 | README | **compress** (Step 1) | 保留工程边界 ~120–220 行；协议细节归档 |
| `STATUS.md` (117 行) | 当前 Gate / 能力 / backlog | **yes** | 与 PROJECT_SOURCE / CODEX_TASKS / gpt 摘要 | ✓ | **keep + compress** (Step 1) | 唯一 project status；写入 `WORKSTATION_SIMPLIFICATION_IN_PROGRESS` |
| `PROJECT_SOURCE.md` (153 行) | 长期定位与职责表 | **yes** | 状态段与 STATUS 重复 | ✓ | **keep + rewrite WS model** (Step 1) | 工作站模型 → GitHub+GPT+Codex |
| `DECISIONS.md` | 决策表 + ADR 索引 | **yes** | ADR 细节在 `docs/decisions/` | ✓ | **keep**；Step 1 增简化决策 | — |
| `CODEX_TASKS.md` (99 行) | Codex 任务池 / wave 顺序 | 半 canonical | 与 STATUS / tasks/current / Issue | ✓ | **deprecate pointer** (Step 2) | GitHub Issues + STATUS |
| `tasks/current.md` (1235 行) | “当前任务”+ 长历史 changelog | AGENTS 强制读，但非唯一 | 与 docs/tasks + reports 重复 | ✓ | **compat pointer** (Step 2)；历史归档 | `docs/archive/task-history/` |
| `CODEBUDDY.md` | CodeBuddy compatibility 入口 | compat only | REMOTE / AI_WECHAT / WorkBuddy 文档 | AGENTS 间接 | **archive** (Step 3) | `docs/archive/workstation/` |
| `CLAUDE.md` | 兼容入口 → AGENTS | pointer | — | — | **keep**（薄指针） | — |
| `TESTING.md` | 测试与 Gate 命令 | deep canonical | gpt 摘要 12 | ✓ | **keep** | — |
| `docs/DEVELOPMENT.md` | — | **缺失** | — | — | **create** (Step 1) | 唯一开发流程 |

### 1.2 Deep business canonical（禁止当工作站精简误改事实）

| Path | Disposition |
|---|---|
| `docs/ARCHITECTURE.md` | **keep** — 不改业务架构事实 |
| `docs/DATA_CENTER.md` | **keep** |
| `docs/BACKTEST_ENGINE.md` | **keep** |
| `docs/SIGNAL_EVENTS.md` | **keep** |
| `docs/strategy/**`、`docs/decisions/ADR-*`（业务 ADR） | **keep** |
| `docs/tasks/<业务 TASK>.md` | **keep** 历史/高风险契约；普通小任务不再强制新建 |

### 1.3 `docs/workstation/**`（active）

| Path | Duty | Disposition (Step 3) |
|---|---|---|
| `GITHUB_NATIVE_CONTROL_PLANE.md` | 五层事实 / 生命周期 | **archive** → 由 DEVELOPMENT + AGENTS 替代 |
| `WORKBUDDY_*.md`（5） | WorkBuddy 正式协议 | **archive** |
| `HOME_DEVELOPMENT.md` / `REMOTE_DEVELOPMENT.md` | 双入口 | **archive** |
| `ROUTING_POLICY.md` / `CODEX_PROFILES.md` | 模型路由 / profile | **archive**（profile 安装说明可留 ops 附录） |
| `WRITER_LOCK_HANDOFF.md` | writer lock 协议 | **archive**（能力迁 engineering 后） |
| `ENVIRONMENT_FAIL_CLOSED.md` | fail-closed 原则 | **compress into DEVELOPMENT/AGENTS** 后 archive 或保留短链 |
| `TASK_SCHEMA_V2.md` | TASK 规范 | **archive** active 强制；历史契约仍可读 |
| `TASK_SCHEMA_V3_DESIGN.md` | 未落地设计 | **archive** |
| `GITHUB_NATIVE_ISSUE_CONTRACT.md` | Issue 元数据契约 | **archive** 或压缩进 DEVELOPMENT「复杂任务 Issue 字段」 |
| `ARCHITECTURE.md`（workstation） | 控制面架构 | **archive** |
| `WORKSTATION_DOCUMENT_MAP.md` | 导航 | Step 3 后改为指向 archive 索引或删除 active 导航 |
| `WORKSTATION_MIGRATION_INVENTORY.md` | 2026-07-16 迁移记录 | **archive**（历史） |
| `WORKSTATION_UPGRADE_ACCEPTANCE.md` / `OPERATIONS_CHECKLIST.md` / `SELF_CHECK.md` / `GITHUB_LIFECYCLE_CLEANUP.md` | 验收与运营 | **archive** |
| `GITHUB_AI_ENGINEERING_V2_UPGRADE_PLAN.md` | 已 superseded | **archive** |
| `demos/*` | Demo 证据 | **archive** |
| `archive/pre-workbuddy-v3/**` | 已归档 | **keep archived**；可再迁入 `docs/archive/workstation/` |
| **本文件** `WORKSTATION_SIMPLIFICATION_INVENTORY.md` | 精简依赖图 | **keep** 至 Step 7；最终可移入 `docs/archive/workstation/` |

### 1.4 `docs/workflows/**`

| Path | Disposition |
|---|---|
| `ai_delivery_workflow.md` / `status_machine.md` / `work_levels.md` / `workbuddy_*.md` / `dispatcher_fault_handling.md` | **archive**（Step 3） |
| `GITHUB_DRAFT_PR_WORKFLOW.md` / `GPT_GITHUB_REVIEW_WORKFLOW.md` | **compress into DEVELOPMENT** 后 archive 或保留极短版 |
| `github_labels.md` / `github_issue_trace_workflow.md` | **archive** |
| `worktree_registry.md` | 生成物；**keep or ignore** — 非执行规范 |

### 1.5 GPT / project_sources

| Path | Disposition |
|---|---|
| `project_sources/**`（根目录整树） | **archive** → `docs/archive/gpt-sources/`（Step 3）；退出 active |
| `docs/gpt/project_sources/01–13` | **archive** |
| `docs/gpt/project_sources/00-INDEX.md` | Step 1–3 改为指向 README/STATUS/AGENTS/DEVELOPMENT，或一并 archive |
| `docs/gpt/CURRENT_STATE.md` / `NEXT_STEPS.md` / `PROJECT_SNAPSHOT.md` | **archive**（stale；以 STATUS 为准） |
| `docs/gpt/PROJECT_SOURCE_MANIFEST.md` | Step 1 可标 deprecated；Step 3 archive |
| `docs/gpt/GITHUB_READ_ORDER.md` | **compress** → DEVELOPMENT / README |
| `docs/gpt/*_REVIEW_PACKAGE.md` | **archive**（任务证据） |
| `docs/CODEX_HANDOFF.md` | **compress** 或 archive；不再要求读十几份工作站文档 |
| `docs/AI_WECHAT_WORKFLOW.md` | **archive**（企微完整链路退出正式架构） |
| `docs/AGENT_WORKFLOW.md` | **archive** 或折叠进 DEVELOPMENT |

### 1.6 Skills / prompts（控制面相关）

| Path | Disposition |
|---|---|
| `.agents/skills/guiyi-workstation-orchestrator/**` | Step 6 候选删除（依赖 WorkBuddy） |
| `.agents/skills/guiyi-delivery-team/**` | Step 6 评估；若仅绑定旧 facade → archive/delete |
| `.agents/skills/local-workstation/**` | Step 6 评估 |
| `prompts/workbuddy-*.md` / `prompts/codebuddy-*.md` | **archive** (Step 3/6) |

---

## 2. State-source inventory

| Source | Role today | Active canonical? | Final recommendation |
|---|---|---|---|
| GitHub Issue / PR | 任务生命周期、远程入口 | **yes** | **保留为唯一任务生命周期** |
| `STATUS.md` | 项目阶段 / Gate | **yes** | **保留为唯一项目当前状态** |
| `DECISIONS.md` / ADR | 长期决策 | **yes** | **保留** |
| `docs/tasks/<TASK_ID>.md` | 高风险执行契约 | **yes（任务级）** | **仅高风险/历史保留**；普通任务不强制 |
| `data/reports/**` / 已合并 PR | 版本化证据 | **yes（证据）** | **保留** |
| `CODEX_TASKS.md` | 第二任务池 | 半 | **退出** → deprecated 指针（Step 2） |
| `tasks/current.md` | 长历史日志 | 被强制读 | **退出膨胀职责** → 最小兼容指针（Step 2）；历史归档 |
| `.ai/results` | local-first 执行证据 | **否** | **非 canonical**；Step 6 后不再作为控制面约定 |
| `.ai/approvals` | Plan 审批 JSON | 旧控制面 | **兼容期保留**；Step 6 删除运行时要求（高风险改为 Issue/PR 人工批准） |
| `.workbuddy/memory` | 会话 | **否**（仓内不存在） | **永不 canonical**；Step 6 gitignore |

**目标状态模型：**

```text
项目当前状态：STATUS.md
任务生命周期：GitHub Issue / PR
长期决策：DECISIONS.md / ADR
高风险执行契约：必要时 docs/tasks/<TASK_ID>.md
运行证据：版本化报告或 PR evidence
其他状态源：退出 active canonical
```

---

## 3. Script / control-plane inventory

### 3.1 Call graph (simplified)

```text
workbuddy_task.sh (remote facade / whitelist)
        │
dispatch_task.sh (stage orchestrator + gates)
        │
   ┌────┼──────────────────────────────┐
   │    │                              │
route_task.sh    scripts/env/check_task_env.sh
   │             bootstrap_worktree_env.sh
   ▼
codex_plan / codex_dev / run_tests / collect_result / codex_review
   │
gate libs: _dirty_gate / _approve / _scope / _external_disk / _work_level
locks: writer_lock.sh / resource_lock.sh
python: lib/*.py (router, approval, status machine, schema, …)
```

CI / Make：

| Entry | Invokes | Disposition |
|---|---|---|
| `Makefile` `workstation-doctor` | `scripts/ai/workstation_doctor.sh` | Step 4 起改调 engineering 或保留 doctor 至 Step 6 迁移 |
| `Makefile` `workstation-test` | doctor + `pytest tests/workstation` | Step 6 后改为 `tests/engineering` + 必要回归 |
| `.github/workflows/workstation-test.yml` | 同上 | Step 6 仅删对旧控制面的强制依赖；不新增复杂自动化 |

### 3.2 Major entrypoints — disposition for simplify

图例：

- **migrate-gates** = Step 4 提取能力到 `scripts/engineering/**`
- **deprecate** = Step 4 加提示，行为不变
- **delete-step6** = Step 5 Pilot 通过且依赖证明后删除
- **keep-capability** = 能力必须保留（可换实现位置）

| Path | Callers | Writes? | Real Gate? | Disposition |
|---|---|---|---|---|
| `scripts/ai/dispatch_task.sh` | workbuddy、doctor、tests、docs、AGENTS | yes（.ai/results, locks, status） | **orchestrator + gates** | **deprecate** → **delete-step6**（能力已迁 engineering 后） |
| `scripts/ai/workbuddy_task.sh` | docs、prompts、skills、tests | indirect | facade / whitelist | **deprecate** → **delete-step6** |
| `scripts/ai/route_task.sh` + `lib/route_task.py` | dispatch、doctor、tests | no（stdout） | 模型路由 / 角色策略 | **deprecate** → **delete-step6**（简化后不需要模型路由） |
| `scripts/ai/approve_task.sh` + `approval.sh` + `lib/approval_manager.py` | workbuddy、dispatch、tests | `.ai/approvals` | **yes** | **migrate-gates**（生产写入确认）→ 旧文件 delete-step6 |
| `scripts/ai/run_tests.sh` | dispatch、codex_dev | `.ai/results` logs | **yes**（命令 allowlist） | **migrate-gates** → `scripts/engineering/test.sh` |
| `scripts/ai/collect_result.sh` | dispatch result | bundles | evidence | 普通任务不需要；**deprecate** → delete-step6 |
| `scripts/env/check_task_env.sh` | dispatch、doctor、tests | optional json | **yes**（fail-closed，不打印 secret） | **migrate-gates** → preflight |
| `scripts/env/bootstrap_worktree_env.sh` | tests、docs | `.env` on `--apply` | **yes**（production confirm） | **keep-capability** / migrate |
| `scripts/ai/workstation_doctor.sh` | Make/CI | no | health probes | **migrate-gates** → preflight/runtime-health |
| `scripts/ai/_dirty_gate_lib.sh` | dispatch | no | **yes** | **migrate-gates** |
| `scripts/ai/_external_disk_lib.sh` | dispatch | no | **yes** | **migrate-gates** |
| `scripts/ai/_scope_report_lib.sh` | dispatch | reports | **yes** | 评估：普通工程可用 `git diff`；高风险保留概念 |
| `scripts/ai/writer_lock.sh` | dispatch | `.ai/writer-locks` | **yes**（防双写） | 简化后靠「单 worktree 纪律」；**deprecate** → delete-step6 if unused |
| `scripts/ai/resource_lock.sh` | dispatch | locks | **yes**（data-writer） | **keep-capability** 理念；实现可进 production-write-check |
| `scripts/ai/codex_plan.sh` / `codex_dev.sh` / `codex_review.sh` | dispatch | logs | stage wrappers | **deprecate** → delete-step6（Codex 由用户/Issue 直接驱动） |
| `scripts/ai/lib/model_router.py` | route | no | 路由模拟 | **delete-step6** |
| `scripts/ai/lib/status_machine.py` / `task_status_transition.py` | dispatch | TASK status | 状态机 | **delete-step6** |
| `scripts/ai/lib/schema_validator.py` | dispatch | no | TASK schema 强制 | **delete-step6**（普通任务不强制 TASK） |
| Compat aliases (`codexplan.sh`, `runtests.sh`, …) | legacy | no | no | **delete-step6** |
| `scripts/ai/run_v12_post_auth_e2e.sh` | archive docs | many | legacy e2e | **delete-step6** |
| GitHub sync (`update_pr_from_result.sh`, `comment_issue_result.sh`, …) | workbuddy/docs | GitHub w/ confirm | status sync | Step 6：无调用可删；有人工价值可留薄脚本 |

**尚不存在（Step 4 新建）：**

```text
scripts/engineering/preflight.sh
scripts/engineering/test.sh
scripts/engineering/check-secrets.sh
scripts/engineering/runtime-health.sh
scripts/engineering/production-write-check.sh
```

### 3.3 Must-keep safety capabilities（不得因精简丢失）

| Capability | Current home | Survivor after Step 4–7 |
|---|---|---|
| Secret / env 不打印真值 | `check_task_env`、`redact_evidence`、doctor | `check-secrets.sh` + redact 保留或并入 test |
| Dirty worktree / 非 main 开发提示 | `_dirty_gate_lib`、`_work_level_lib` | `preflight.sh` |
| Branch / git root 检查 | env / work_level | `preflight.sh` |
| 自动化测试聚合 + 安全退出码 | `run_tests.sh`、Make | `test.sh` |
| Production write 显式确认 fail-closed | approve + bootstrap `--confirm-production` | `production-write-check.sh` |
| Data / mount / DB 边界 fail-closed | `_external_disk_lib`、env bootstrap | preflight + production-write-check |
| Runtime health 只读 | doctor / `_runtime_gate_lib` | `runtime-health.sh` |
| 禁止自动 merge / push / deploy | run_tests allowlist、docs | DEVELOPMENT + test allowlist + 用户纪律 |
| 高风险人工审批 | `.ai/approvals` + Issue | **Issue/PR 批准**（替代普通任务 approvals） |

---

## 4. Direct archive candidates（仍须 Step 3 引用修复后移动）

可先归档、通常无运行时加载（仍要 `git grep`）：

- `docs/workstation/demos/**`
- `docs/workstation/GITHUB_AI_ENGINEERING_V2_UPGRADE_PLAN.md`
- `docs/workstation/archive/pre-workbuddy-v3/**`（已 archive，可上收）
- 根目录 `project_sources/**`（整树）
- `docs/gpt/CURRENT_STATE.md`、`NEXT_STEPS.md`、`PROJECT_SNAPSHOT.md`
- 多数 `docs/workflows/workbuddy_*.md`、`work_levels.md`、`status_machine.md`

**不可仅因「看起来旧」直接删：**

- 仍被 `tests/workstation` 读取的 fixtures / scripts
- CI 调用的 `workstation_doctor.sh`
- 业务 `docs/tasks/**` 与 `data/reports/**`
- 任何仍被 `Makefile` / launchd / deploy 引用的路径（deploy 默认本精简不改）

---

## 5. Must deprecate-then-delete（不可 Step 0–3 直接删）

| Item | Why wait |
|---|---|
| `dispatch_task.sh` / `workbuddy_task.sh` | 测试与文档大量引用；须先有 engineering 替代 + Pilot |
| `tasks/current.md` 文件本身 | 旧脚本可能解析；Step 2 缩指针，Step 6 再评估删除 |
| `CODEX_TASKS.md` | 入口链接多；Step 2 指针，确认无脚本硬依赖后再删 |
| `.ai/schema/task.schema.json` | schema_validator / tests | Step 6 |
| `tests/workstation/**` 全量 | 绑旧控制面；Step 4 建 `tests/engineering` 后，Step 6 删无用用例 |

---

## 6. Risks and dependencies for Step 1–7

| Step | Depends on | Main risks |
|---|---|---|
| **1 Canonical docs** | 本 inventory | AGENTS 压缩误改业务边界；链接失效；与 STATUS 业务 Gate 漂移 |
| **2 State sources** | Step 1 | 归档丢失历史；`tasks/current` 缩指针破坏仍依赖的脚本解析 |
| **3 Docs archive** | Step 0–2 矩阵 | 大量相对链接断裂；误归档业务 deep canonical |
| **4 Engineering entrypoints** | Step 0 脚本表 | 削弱 production-write / secret Gate；新入口仍偷偷依赖 WorkBuddy |
| **5 Real Pilot** | Step 4 | Pilot 做成无害 Demo；或误选 DB/策略高风险任务 |
| **6 Legacy removal** | Step 5 `REAL_GITHUB_CODEX_PILOT_PASSED` | CI 断裂；漏引用；误删 env/secret 能力 |
| **7 Final freeze** | Step 6 | 用文档宣称完成但测试失败；残留 active 旧引用 |

**StopGates（手册原样）：**

- Step 0 无可靠依赖图 → 禁止 Step 1  
- Step 5 未通过真实已合并 Pilot → 禁止 Step 6  
- Gate 削弱或业务回归 → 回滚该删除项  

---

## 7. Suggested Step 4 engineering mapping

| New script | Extract from |
|---|---|
| `preflight.sh` | doctor + dirty + branch + mount 探针（只读） |
| `test.sh` | `run_tests.sh` 的安全聚合思想 + 仓库标准测试入口 |
| `check-secrets.sh` | doctor secret scan + redact 规则（永不打印值） |
| `runtime-health.sh` | doctor / runtime gate 只读部分 |
| `production-write-check.sh` | approve production flag + bootstrap confirm 语义 |

新脚本 **禁止** 依赖：WorkBuddy、CodeBuddy、L0/L1/L2、model router、Issue status machine。

---

## 8. Step 0 acceptance checklist

- [x] 文档职责与重复关系已记录
- [x] 状态源冲突与目标模型已明确
- [x] 脚本调用关系与处置已记录
- [x] 必须保留的安全 Gate 已列出
- [x] 可直接归档项 vs 必须先 deprecated 项已区分
- [x] Step 1–7 风险与依赖已给出
- [x] 明确当前为 non-blocking support 上的进一步精简，非重建
- [x] **未修改** 任何现有脚本行为 / 业务代码 / 数据

---

## 9. Verification commands run

```bash
git status --short --branch
find docs/workstation docs/workflows docs/gpt project_sources -type f | sort
find scripts/ai scripts/env tests/workstation -type f | sort
git grep -l "WorkBuddy|CodeBuddy|dispatch_task|tasks/current|CODEX_TASKS" -- . | wc -l
# → ~205 matching files
```

本步不修改脚本；`git diff --check` 仅应覆盖本 inventory 与 TASK 文件新增。
