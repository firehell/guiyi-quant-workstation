# WS-FINAL-CLEANUP-00-INVENTORY

| Field | Value |
|---|---|
| Task ID | `WS-FINAL-CLEANUP-00-INVENTORY` |
| Step | 0（只读盘点；禁止删除/改行为） |
| Branch | `codex/ws-final-cleanup-00-inventory` |
| Worktree | `/Volumes/扩展盘/GuiyiWorktrees/guiyi-ws-final-cleanup-00` |
| Baseline | `origin/main` @ `300c31c0`（`fix: raise HTDY channel contrast on dark chart theme`） |
| Status | `INVENTORY_READY` |
| Risk | R0（仅新增本文件） |
| Date | 2026-07-20 |

## Objective

冻结《最终清理与加固》删除/保留矩阵，作为 Step 1–5 串行依据。原则：**不因“已归档”自动保留**；Git 历史已保存。本步不改任何现有文件。

## Stop Gate

本 PR **未 merge 前**，禁止进入 Step 1+（改 `CANONICAL_DOCS`、删 stub、迁 Gate、改 CI/STATUS/ADR）。

## Search evidence（本 worktree）

```bash
rg -n "docs/gpt|docs/workstation|docs/workflows|docs/archive/gpt-sources|docs/archive/workstation|docs/archive/task-history|CODEX_TASKS|tasks/current|CODEBUDDY|CODEX_HANDOFF|update_project_source_index|scripts/ai|scripts/env|configs/ai|WorkBuddy|CodeBuddy|dispatcher|L0/L1/L2|\.ai/results" --glob '!data/**' --glob '!node_modules/**' .

rg -n "CANONICAL_DOCS|PROJECT_INVENTORY|worktree_registry|resource_lock|redact_evidence|bootstrap_worktree_env|check_task_env|production-write-check|workstation-test" .
```

业务保护：本 worktree 自 `origin/main` 干净检出；**未**带入主仓 dirty 分支上的 `data/reports/jm_live_t3_s6_05/**` untracked 残留。

---

## 高风险 caller / Stop Gate 问题（摘要）

| 问题 | 证据 | 后续 Step |
|---|---|---|
| `data_stage_closure.py` 仍把已删除的 GPT/多状态源标为 `CANONICAL_DOCS` | `tasks/current.md`、`docs/CODEX_HANDOFF.md`、`docs/gpt/CURRENT_STATE.md`、`NEXT_STEPS.md`、`PROJECT_SNAPSHOT.md`；磁盘上 `docs/gpt/` **仅剩** `README.md` stub，三份 GPT 正文已迁 `docs/archive/gpt-sources/` | **Step 1**（先改 caller，再删 stub） |
| `scripts/docs/update_project_source_index.py` 仍生成旧 GPT 摘要索引 | 硬编码 `docs/gpt/project_sources/*`、`CODEX_TASKS.md`、`tasks/current.md`；仓库内无其他 import/shell 正式调用，但脚本仍可误写 | **Step 1** |
| `docs/ARCHITECTURE.md` 仍描述 WorkBuddy/dispatcher/`scripts/ai` 控制面 | 与 `AGENTS.md` / `DECISIONS.md` / `WORKSTATION_SIMPLIFIED` 冲突 | **Step 1**（文档收敛）或 **Step 5** |
| Engineering Gate 缺口 | `Makefile` `engineering-preflight` 只跑 `preflight` + `check-secrets`；`runtime-health` / `production-write-check` 仅靠 `tests/engineering` 间接覆盖，非显式 make 目标必跑项 | **Step 3** |
| CI / PR template 仍绑定旧控制面语义 | `.github/workflows/workstation-test.yml` path filter 含 `scripts/ai/**`、`scripts/env/**`；PR template 含 L0/L1/L2、`.ai/results`、旧 TASK 字段 | **Step 4** |
| `STATUS.md` 下一入口冲突 | 正文多处写下一步 `S6-05` T3；表格「业务下一入口」仍写 `S6-01` | **Step 5** |
| `ADR-WS-001` vs 当前模式 | ADR 仍要求复用 `dispatch_task.sh` / V2 schema / WorkBuddy；`DECISIONS.md` 已冻结 `WORKSTATION_SIMPLIFIED` + 不重建 dispatcher | **Step 5**（supersede / 修订） |
| `tests/engineering` 仍硬依赖 `scripts/ai/redact_evidence.sh` | 删除 `scripts/ai` 前必须先迁 redact 能力或改测试 | **Step 3**（条件删除前置） |

---

## 表 1 — 确定删除

旧工作站 / GPT 摘要 / 多状态源；**无 active 业务运行时调用**（仅文档互引或已失效路径）。删除前须先完成标注的 caller 修复（多数在 Step 1）。

| # | 路径 | 调用方（当前） | 替代项 | 风险 | 后续 Step |
|---|---|---|---|---|---|
| D1 | `CODEBUDDY.md` | 仅文档/prompts 提及；自身为 archived stub | `AGENTS.md`；历史见 `docs/archive/workstation/CODEBUDDY.md` | 低 | 1→2 |
| D2 | `CODEX_TASKS.md` | `update_project_source_index.py`、`TESTING.md` 链接；非 Issue/PR 生命周期 | `STATUS.md` + GitHub Issue/PR | 低；先停 index 生成 | **1** |
| D3 | `tasks/current.md` | `data_stage_closure.CANONICAL_DOCS`、旧 prompts/templates、index 脚本 | `STATUS.md` + Issue/PR | **中**（closure 文档盘点） | **1** 先改 CANONICAL_DOCS |
| D4 | `docs/CODEX_HANDOFF.md` | 同上 + `prompts/CODEX_TASK_TEMPLATE.md` / `codex-feature.md` | `AGENTS.md` + `docs/DEVELOPMENT.md`；全文在 archive | **中** | **1** |
| D5 | `docs/gpt/README.md`（及已缺失的 `CURRENT_STATE`/`NEXT_STEPS`/`PROJECT_SNAPSHOT` 引用） | `CANONICAL_DOCS` 仍列三份已删文件；strategies/README 链到 `docs/gpt/NEXT_STEPS.md`（断链） | `STATUS.md` / deep canonical；正文在 `docs/archive/gpt-sources/docs-gpt-full/` | **中**（断链 + closure） | **1** |
| D6 | `docs/workstation/README.md` | stub → archive | `docs/DEVELOPMENT.md` | 低 | 1→2 |
| D7 | `docs/workflows/README.md` | stub | `docs/DEVELOPMENT.md` | 低 | 1→2 |
| D8 | `docs/workflows/worktree_registry.md` | 引用已删除的 `scripts/ai/list_worktrees.sh` | 人工 `git worktree list`；勿再当规范 | 低 | 1→2 |
| D9 | `docs/PROJECT_INVENTORY.md` | 指向 `tasks/current` / `docs/gpt/*` 多状态源 | `PROJECT_SOURCE.md` + `STATUS.md` | 低 | **1** |
| D10 | `docs/delivery_checklist.md` | 旧交付清单；非 Stage6 Gate | `docs/DEVELOPMENT.md` + PR template（Step 4 精简后） | 低 | 1→4 |
| D11 | `prompts/CODEX_TASK_TEMPLATE.md`、`codex-feature.md`、`codex-readonly-plan.md`、`task-template.md` 中旧路径指引 | 人工/Agent 阅读入口 | 以 `AGENTS.md` + Issue/PR 为准；可删或改写为最小模板 | 低 | 1→2 |
| D12 | `outputs/WS-V2-009-delivery/**` | 无运行时；历史交付包 | Git 历史 | 低 | **2** |
| D13 | `docs/tasks/workstation/**`（WS-V2-* 计划 6 份） | 无 runtime enforce | archive 或删除；Git 历史 | 低 | **2** |
| D14 | `docs/tasks/DEMO-*.md`、`DEMO-WB-*.md`（5） | 无 runtime | 删除；Git 历史 | 低 | **2** |
| D15 | `docs/tasks/WS-SIMPLIFY-*.md`、`WS-WB-STATE-FIX-001.md`、`V1-WORKSTATION-SUPPORT-MODE-003.md` | 精简过程契约；非业务 Gate | 本 inventory + `docs/archive/workstation/WORKSTATION_SIMPLIFICATION_*` | 低（保留至 Step 2 末亦可） | **2** |
| D16 | `docs/tasks/archive/workstation-legacy/**` | 历史 | 删除或维持 archive 至 Step 2 批量清 | 低 | **2** |
| D17 | `docs/tasks/examples/**`（L1/L2 fixture 等） | 旧 dispatcher 测试夹具引用 | 无（`tests/workstation` 已删） | 低 | **2** |
| D18 | `docs/tasks/TASK_TEMPLATE.md`、`TASK_TEMPLATE_L1.md`、`TASK-2026-07-12-02{0,1,2,3}-workstation-*`、`TASK-2026-07-16-001-control-plane-fix.md`、`TASK-2026-07-11-004-work-levels-*` | 工作站控制面历史 TASK | 业务 TASK 保留；此类归工作站历史 | 低 | **2**（区分规则见下） |
| D19 | 根目录 `tasks/**`（含 `tasks/done`、`tasks/README.md`、旧业务旁路任务） | 兼容指针体系；`tasks/current.md` 已 deprecated | `docs/tasks/<业务TASK>.md` + Issue | 低–中 | **2** |
| D20 | `docs/archive/gpt-sources/**`（~39 files） | 无 Python import；仅文档互指 | Git 历史；`PROJECT_SOURCE.md` / deep canonical | 低；体积清理 | **2** |
| D21 | `docs/archive/workstation/**`（~73 files） | 无 runtime；ADR/README 链接 | Git 历史；精简报告可先摘一句进 DECISIONS | 低 | **2** |
| D22 | `docs/archive/task-history/**`（3 files） | 无 runtime | Git 历史 | 低 | **2** |
| D23 | `scripts/docs/update_project_source_index.py` | **无**其它正式 caller；自身是旧摘要生成器 | 停止生成；导航以根目录 canonical 为准 | **中**（误跑会写回已删路径） | **1** |

**表 1 条目数：23**

---

## 表 2 — 条件删除

须证明：**无 Python import / shell caller / GitHub Actions / launchd / Stage6 Gate caller** 后才可删；或先迁移能力再删。

| # | 路径 | 调用方（当前） | 替代项 / 迁移 | 风险 | 后续 Step |
|---|---|---|---|---|---|
| C1 | `scripts/ai/redact_evidence.sh` + `lib/result_bundler.py` | `tests/engineering/test_engineering_entrypoints.py::test_redact_evidence_*`；`TESTING.md` | 迁入 `scripts/engineering/` 或并入 test helper 后删除 `scripts/ai` | **中**（Secret redact 能力不可丢） | **3** |
| C2 | `scripts/ai/resource_lock.sh` + `lib/resource_lock.py` | 无 dispatcher；schema `configs/ai` 仍有 `resource_locks` 字段；未见 Stage6/launchd 调用 | 能力并入 `production-write-check` 叙事或单独 engineering 工具；确认无 live 脚本引用后删 | **中**（data-writer fail-closed） | **3** |
| C3 | `scripts/ai/` 目录整体 | CI path filter 仍 watch；`docs/ARCHITECTURE.md` 仍描述 | 空目录删除前更新 CI + 文档 | 中 | 3→4 |
| C4 | `scripts/env/check_task_env.sh` | deprecated shim → `preflight`/`check-secrets`；无外部业务 import | 确认无 launchd/cron 后删 | 低 | **3** |
| C5 | `scripts/env/bootstrap_worktree_env.sh` | 独立能力；`production-write-check` 语义相关；未见 Stage6 Gate 硬依赖 | 迁 engineering 或保留至有替代 bootstrap | **中**（可写 `.env`；禁本轮触碰） | **3** |
| C6 | `configs/ai/**`（schemas / profile_templates / model_routing） | 无 dispatcher；可能被人工 Codex profile 使用 | 单独审计后再删；勿与 Stage6 混淆 | 低–中 | **3**（审计）→2 |
| C7 | `CLAUDE.md` | 兼容入口，指向 AGENTS | 可保留为薄指针或删（Agent 生态） | 低 | 2 或保留 |
| C8 | `.github/workflows/workstation-test.yml` 中对 `scripts/ai/**`、`scripts/env/**` 的 path filter | Actions | 改为仅 `scripts/engineering/**` + `tests/engineering/**`（或改名 engineering-test） | 低 | **4** |
| C9 | `Makefile` 别名 `workstation-doctor` / `workstation-test` | 文档与肌肉记忆 | 保留别名一段时间或文档标明 deprecated | 低 | **4** |
| C10 | `.github/PULL_REQUEST_TEMPLATE.md` 中 L0/L1/L2、`.ai/results`、旧 WorkBuddy 字段 | PR 流程 | 收敛为 Issue/PR + engineering checks + 安全清单 | 低 | **4** |
| C11 | `TESTING.md` WorkBuddy V3 / `bash -n scripts/ai/*.sh` 章节 | 人工验证说明 | 改为 engineering 入口章节 | 低 | 3→4 |
| C12 | `docs/decisions/ADR-WS-001-github-native-control-plane.md` 正文中 dispatcher 强制条款 | `DECISIONS.md` ADR 表仍标 Accepted | supersede：保留「Issue/PR 事实面」；废止 dispatcher/WorkBuddy 强制 | **中**（决策一致性） | **5** |
| C13 | `docs/ARCHITECTURE.md` 控制面行 | 读者误判正式架构 | 改为指向 `docs/DEVELOPMENT.md` / engineering | 中 | **1** 或 **5** |
| C14 | `services/quant-api/.../data_stage_closure.py` 内旧 `CANONICAL_DOCS` 与 `docs/gpt/` 分支逻辑 | `scripts/data_stage_closure_audit.py`、`tests/test_data_stage_closure_audit.py`、历史 `data/reports/data_stage_closure/` | 改为根目录 canonical：`README/AGENTS/STATUS/PROJECT_SOURCE/DECISIONS/TESTING` + deep canonical；**不删业务 closure 能力** | **高**（文档盘点分类错误） | **1**（改代码引用，非删模块） |
| C15 | `prompts/gpt-github-pr-review.md` 等仍提 `.ai/results` | 人工 review | 改为 PR evidence / 版本化 `data/reports` | 低 | 4→5 |

**表 2 条目数：15**

> 注：C14 是 **改 caller / 改集合**，不是删除 `data_stage_closure` 业务模块。模块与 Stage6/数据审计相关测试必须保留（见表 3）。

---

## 表 3 — 必须保留

| # | 路径 | 调用方 | 替代项 | 风险（若误删） | 后续 Step |
|---|---|---|---|---|---|
| K1 | `README.md` | 人类入口 | — | 高 | 可在 Step 1 微调链接，不删 |
| K2 | `AGENTS.md` | Agent 硬规则 | — | 高 | 5 可同步 STATUS 引用 |
| K3 | `STATUS.md` | 项目状态唯一摘要 | — | 高；须修 S6-01/S6-05 | **5** 修冲突，不删 |
| K4 | `PROJECT_SOURCE.md` | 导航 / 边界 | — | 高 | 1/5 可去过时指针 |
| K5 | `DECISIONS.md` | 长期决策 | — | 高；须对齐 ADR | **5** |
| K6 | `TESTING.md` | 测试说明 | — | 中；改章节不删文件 | 3→4 |
| K7 | `docs/DEVELOPMENT.md` | 唯一开发流程 | — | 高 | 保留；可补 Gate |
| K8 | Deep canonical：`docs/ARCHITECTURE.md`、`DATA_CENTER.md`、`BACKTEST_ENGINE.md`、`SIGNAL_EVENTS.md`、`INDICATOR_KERNEL.md`、策略/数据相关设计文 | 业务实现与验收 | — | 高 | 1 可改过时控制面句，不删文 |
| K9 | 业务 `docs/tasks/**`（JM/HTDY/DATA/CURSOR/CONSUMER/DIRECTION/FULL-HISTORY/INDICATOR/MARKET 等） | Stage4–6 契约与证据索引 | — | 高 | **2** 分类时保留 |
| K10 | `docs/tasks/JM-LIVE-T3-S6-05.md` 及 S6-02…S6-06、`JM-LIVE-GATE-EVIDENCE.md` | Stage6 主线 | — | **极高** | 保留 |
| K11 | `scripts/engineering/**`（`preflight` / `check-secrets` / `test` / `runtime-health` / `production-write-check`） | Makefile、CI、AGENTS | — | 高 | **3** 补齐显式 Gate，不删 |
| K12 | `tests/engineering/**` | CI | — | 高 | 3 可改 redact 路径 |
| K13 | Stage6 / 数据业务脚本与测试（如 `scripts/data_stage_closure_audit.py`、`services/quant-api/.../data_stage_closure.py` **模块本身**、JM live 相关、ingest、golden query 等） | 业务 Gate | — | 极高 | 禁止当「工作站垃圾」删 |
| K14 | 版本化证据：`data/reports/**`（含 consumer golden、stage45、jm_* 等已提交证据） | STATUS / 任务契约引用 | — | 极高 | 不删；主仓 untracked T3 残留属另一业务线 |
| K15 | `.agents/skills/**`（业务 skills；非已删 workstation orchestrator） | Cursor/Codex | — | 中 | 保留 |
| K16 | `.cursor/rules/**` | 编辑器规则 | — | 中 | 保留 |
| K17 | `deploy/launchd/**`、业务 `scripts/dev-*.sh` / `install-local-services.sh` | 本地运行 | — | 高 | 保留；与旧 dispatcher 无关 |
| K18 | 本文件 `docs/tasks/WS-FINAL-CLEANUP-00-INVENTORY.md` | Step 1–5 依据 | — | — | 全程保留至清理收口 |

**表 3 条目数：18**

---

## 工作站历史 TASK vs 业务 TASK（Step 2 分类规则）

| 类别 | 识别特征 | Step 2 动作 |
|---|---|---|
| **工作站历史** | `docs/tasks/workstation/**`、`DEMO-*`、`WS-SIMPLIFY-*`、`WS-WB-*`、`V1-WORKSTATION-*`、`TASK-*-workstation-*`、`control-plane`、`work-levels`、`archive/workstation-legacy`、`examples` L0/L1/L2 fixture | 删除或不再保留在 active tree（Git 历史足够） |
| **业务 TASK** | JM / HTDY / DATA / FULL-HISTORY / CONSUMER / INDICATOR / MARKET / CURSOR Wave / Stage4–6 / strategy validation / live gate evidence | **必须保留** |
| **灰区** | 早期 `TASK-2026-07-11/12` 中同时含数据修复与工作站 CI 收口 | 按正文是否仍被 `STATUS`/`DATA_CENTER`/业务脚本引用决定；默认偏保留业务证据链 |

---

## Step 映射（1–5）

| Step | 主题 | 本 inventory 主要项 |
|---|---|---|
| **1** | Canonical / 旧摘要 caller | D2–D5、D9、D23；**C14**（`CANONICAL_DOCS`）；`update_project_source_index.py`；断链 `docs/gpt/*`；可选修 `ARCHITECTURE` 控制面句 |
| **2** | 历史 TASK / archive / outputs / 根 `tasks/` | D12–D22；工作站 vs 业务分类 |
| **3** | Engineering Gate 加固 | C1–C6；补 `check-secrets` / `test.sh` / `runtime-health` / `production-write-check` 显式入口与文档；迁 redact/lock |
| **4** | CI / Makefile / PR template | C8–C11；去掉 ai/env path 强制；精简 PR 字段 |
| **5** | STATUS / ADR / DECISIONS 对齐 | S6-01 vs S6-05；**ADR-WS-001** supersede；C12–C13 |

Step 6（若手册有）：仅在 1–5 merge 后做最终 grep 收口与残留删除，**本轮不做**。

---

## 验收（本 Step）

```bash
git diff --check
git diff --stat
# 期望：仅新增 docs/tasks/WS-FINAL-CLEANUP-00-INVENTORY.md
```

- [x] 独立 worktree + 分支自 `origin/main`
- [x] 未修改现有文件；未触碰 `.env` / `data/raw` / `data/parquet`
- [x] 未带入 JM T3 untracked 报告
- [x] 三表冻结 + 高风险 caller 标明
- [ ] PR merge（**用户人工**；本代理不 merge）

## Next

用户 merge 本 PR 后，再开 **Step 1** 分支改 `CANONICAL_DOCS` 与旧摘要生成器（仍禁止大范围删除，直至 Step 1 验收）。
