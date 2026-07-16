# GitHub Native V3 Baseline

更新时间：2026-07-14

任务：`WS-GH-001`

审计基线：

- 仓库：`firehell/guiyi-quant-workstation`
- 本地路径：`/Volumes/扩展盘/guiyi-quant-workstation`
- 当前分支：`main`
- 当前 HEAD：`570dc665 文档更新`
- 远端：`origin git@github.com:firehell/guiyi-quant-workstation.git`
- 工作区起始状态：存在未跟踪项 `.kiro/` 与 `docs/workstation/GITHUB_AI_ENGINEERING_V2_UPGRADE_PLAN.md`

本文件冻结 GitHub Native V3 升级前的控制平面基线。WS-GH-001 只做只读审计和文档记录；不修改业务代码、脚本行为、数据、数据库、配置、`.env`、Parquet、manifest 或运行环境。

## 1. 结论

当前工作站控制平面已经具备 V2 级别的 TASK、dispatcher、审批、风险、worktree、scope、resource lock、evidence、runtime gate、Issue 留痕和 workstation tests。V3 不应重建这些能力。

V3 的真实升级点是 GitHub-native 控制平面：

- 从 GitHub Issue 直接解析任务、分支和 TASK。
- 接管 GPT 创建的远程 task branch。
- 建立 Draft PR / PR 模板和 GPT PR Review 协议。
- 把 Issue、TASK、PR、CI、`.ai/results/` 的责任边界写清。
- 将脱敏执行摘要回填 Issue / PR，而不是让用户手工搬运文件。

## 2. 已有能力矩阵

| 能力 | 当前状态 | 证据 | V3 处置 |
|---|---|---|---|
| 项目事实源 | 已有 | `PROJECT_SOURCE.md`、`STATUS.md`、`DECISIONS.md`、`CODEX_TASKS.md`、`tasks/current.md` | 复用 |
| Agent 边界 | 已有 | `AGENTS.md`、`CODEBUDDY.md` | 复用并按 V3 修订 |
| 工作级别 | 已有 | `docs/workflows/work_levels.md` | 复用 |
| 统一 dispatcher | 已有 | `scripts/ai/dispatch_task.sh` | 复用 |
| Stage gate | 已有 | `dispatch_task.sh`、`docs/workflows/status_machine.md`、`scripts/ai/lib/status_machine.py` | 复用 |
| Plan / Dev / Test / Review / Result | 已有 | `codex_plan.sh`、`codex_dev.sh`、`run_tests.sh`、`codex_review.sh`、`collect_result.sh` | 复用 |
| Pause / Resume / Cancel / Status | 已有 | `dispatch_task.sh` control stages、`scripts/ai/lib/dispatch_control.py` | 复用 |
| V2 Task Schema | 已有 | `docs/workstation/TASK_SCHEMA_V2.md`、`configs/ai/schemas/task-v2.0.schema.json` | 复用 |
| 旧 TASK 兼容读取 | 已有 | `scripts/ai/lib/compat_reader.py`、`tests/workstation/test_compat_reader.py` | 复用 |
| 审批凭证 | 已有 | `scripts/ai/approve_task.sh`、`scripts/ai/lib/approval_manager.py`、`configs/ai/schemas/approval-v3.0.schema.json` | 复用 |
| 风险模型 | 已有 | `risk_level` 字段、`scripts/ai/lib/risk_resolver.py` | 复用 |
| Worktree gate | 已有 | `init_task_worktree.sh`、`_work_level_lib.sh`、`tests/workstation/test_worktree_gate.py` | 复用 |
| Branch gate | 已有 | `dispatch_task.sh`、`tests/workstation/test_task_router.py` | 复用 |
| Scope gate | 已有 | `_scope_report_lib.sh`、`collect_result.sh` | 复用 |
| Dirty workspace gate | 已有 | `_dirty_gate_lib.sh` | 复用 |
| Writer lock | 已有 | `writer_lock.sh`、`scripts/ai/lib/writer_lock.py` | 复用 |
| Resource lock | 已有 | `resource_lock.sh`、`scripts/ai/lib/resource_lock.py` | 复用 |
| Runtime gate ledger | 已有 | `_runtime_gate_lib.sh`、`scripts/ai/lib/runtime_gate_ledger.py`、`configs/ai/schemas/runtime-gate-daily.schema.json` | 复用 |
| Result bundle | 已有 | `collect_result.sh`、`make_delivery_summary.sh`、`result_bundler.py` | 复用 |
| Evidence index / redaction | 已有 | `_evidence_lib.sh`、`redact_evidence.sh`、`test_redaction.py` | 复用 |
| GitHub Issue 创建 | 已有 | `create_issue_from_task.sh` | 复用，但方向仍是 local TASK -> Issue |
| GitHub Issue 回填 | 已有 | `comment_issue_result.sh`、`update_issue_status.sh` | 复用并扩展到 PR 摘要 |
| GitHub Actions workstation tests | 已有 | `.github/workflows/workstation-test.yml` | 复用并修 CI 基线问题 |

## 3. 当前 GitHub 集成能力

### 3.1 已有

- `.github/ISSUE_TEMPLATE/task.md`：标准任务 Issue 模板。
- `.github/ISSUE_TEMPLATE/config.yml`：关闭 blank issue，并链接 Issue 留痕流程。
- `.github/workflows/workstation-test.yml`：在 `scripts/ai/**`、`scripts/env/**`、`tests/workstation/**`、`configs/ai/**`、`Makefile`、workflow 自身变化时运行 workstation tests。
- `scripts/ai/create_issue_from_task.sh`：从本地 TASK 创建 GitHub Issue。
- `scripts/ai/link_task_issue.sh`：把 Issue 编号回填 TASK 元信息。
- `scripts/ai/comment_issue_result.sh`：将 plan / test / delivery 结果评论到 linked Issue。
- `scripts/ai/update_issue_status.sh`：同步 Issue `status/*` label，并可更新 TASK Status。

### 3.2 安全边界

- Issue 评论与状态更新默认阻断外部写入，必须传 `--confirm-issue-ops`。
- `update_issue_status.sh` 默认不关闭 Issue；只有显式 `--close` 才关闭。
- `CODEBUDDY.md` 明确禁止自动 push、merge、release、deploy 或创建 PR，除非用户单独授权。
- `AGENTS.md` 与 `CODEBUDDY.md` 均禁止读取、显示或提交凭据。

### 3.3 缺口

| 缺口 | 当前观察 | V3 后续 Step 输入 |
|---|---|---|
| Issue-first bootstrap | 未发现 `Issue #N -> branch/TASK/worktree` 的统一入口 | 需要新增只读解析 + fetch + worktree 接管脚本 |
| 远程 task branch 接管 | `init_task_worktree.sh` 支持从 TASK 创建本地 worktree，但默认不是从 Issue/remote branch 入口 | 需要支持 GPT 创建的 `task/<TASK_ID-slug>` 分支 |
| Draft PR 创建 | 未发现 PR 创建脚本或协议 | 需要 PR 模板与受控 Draft PR 创建/更新流程 |
| GPT PR Review 协议 | 未发现正式 PR review checklist | 需要文档化 GPT 审查输入、输出和禁止项 |
| PR template | `.github/` 当前没有 pull request template | 需要新增 `.github/pull_request_template.md` 或等价模板 |
| PR 状态回填 | Issue 回填已有，PR 摘要回填未见统一入口 | 需要定义脱敏摘要写入 PR comment/body 的规则 |
| GitHub-native task source | 当前 canonical 仍是本地 TASK，Issue 是远程留痕源 | V3 应改为 GitHub 创建任务空间，但 TASK 仍是执行契约 |

## 4. 仍依赖人工复制的节点

| 节点 | 当前规则或文档 | 问题 |
|---|---|---|
| WorkBuddy 生成 TASK | `docs/workflows/ai_delivery_workflow.md`、`docs/workstation/REMOTE_DEVELOPMENT.md` | V3 目标是 GPT 可直接创建 Issue、task branch、TASK、Draft PR |
| 用户复制 TASK / Prompt | `github_issue_trace_workflow.md`、`CODEBUDDY.md` | 仍以本地 TASK_ID 为主要入口，不自然支持 Issue-first |
| GPT 外部审查 | `AGENTS.md` 中仍描述为人工粘贴 diff | 与 GPT 可读 private GitHub 仓库的新能力不一致 |
| GPT Project Sources | `docs/gpt/project_sources/`、`docs/gpt/PROJECT_SOURCE_MANIFEST.md` | 仍用于人工投喂包，V3 后应降级为兼容/离线快照 |
| 结果回填浏览器 GPT | 当前依赖用户同步文件或摘要 | V3 应让 GPT 直接读 Issue / PR / commits / CI |
| Draft PR | 当前没有标准模板和创建入口 | 无法把交付 diff、CI 和 review 串成唯一交付面 |

## 5. 过时文档和规则

以下不是要删除的文件，而是 V3 后续要修订或降级的规则：

| 文件 | 过时点 | 建议 |
|---|---|---|
| `AGENTS.md` | 将 ChatGPT 主要定义为“外部审查（人工粘贴 diff，不接入 IDE）” | 修订为 GPT 可读 GitHub，但仍禁止直接写业务代码和 main |
| `CODEBUDDY.md` | 七命令协议以 `TASK_ID` 为中心；L2 无 Issue 时停止 | 保留兼容，同时新增 Issue-first 输入 |
| `docs/workflows/github_issue_trace_workflow.md` | Lean V1 流程是 WorkBuddy TASK -> 本地脚本创建 Issue | 改为 V3 四层事实模型：main docs / TASK / Issue / PR / local evidence |
| `docs/workstation/ARCHITECTURE.md` | 双入口仍是 Home GPT/Work 与 Remote WorkBuddy 生成 TASK | 更新为 GitHub-native 同一任务空间 |
| `docs/workstation/HOME_DEVELOPMENT.md` | 居家入口仍偏向本地 TASK 落盘 | 增加 GPT + GitHub 创建任务空间路径 |
| `docs/workstation/REMOTE_DEVELOPMENT.md` | 远程入口仍要求用户给 TASK_ID | 增加 CodeBuddy 接收 Issue #N / PR #N |
| `docs/workflows/ai_delivery_workflow.md` | L2 canonical 仍以 WorkBuddy 生成 Task Bundle 开始 | 保留兼容，新增 GitHub-native canonical |
| `docs/gpt/project_sources/**` | 作为人工上传给浏览器 GPT 的主路径 | V3 后降级为快照/备份，不反向成为事实源 |
| `docs/workstation/GITHUB_AI_ENGINEERING_V2_UPGRADE_PLAN.md` | 当前是未跟踪草案，且命名为 V2 | 先确认是否纳入 Git；后续与 V3 文档对齐 |

## 6. 必须保留的兼容接口

V3 升级不得破坏以下接口：

- `scripts/ai/dispatch_task.sh <TASK_ID> <stage> [--json]`
- `scripts/ai/init_task_worktree.sh --task <TASK_ID>`
- `scripts/ai/create_issue_from_task.sh docs/tasks/<TASK_ID>.md`
- `scripts/ai/link_task_issue.sh <TASK_ID> <ISSUE_NUMBER> [task_file]`
- `scripts/ai/comment_issue_result.sh <TASK_ID> <plan|test|delivery> [task_file]`
- `scripts/ai/update_issue_status.sh <TASK_ID> <STATUS> [task_file]`
- `scripts/ai/approve_task.sh --task <TASK_ID>`
- `scripts/ai/run_tests.sh --task <TASK_ID>`
- `scripts/ai/collect_result.sh --task <TASK_ID>`
- `scripts/ai/make_delivery_summary.sh --task <TASK_ID>`
- V2 YAML frontmatter TASK。
- 旧 Markdown TASK 兼容读取。
- `.ai/results/<TASK_ID>/` 结果目录结构。
- `.ai/approvals/<TASK_ID>.json` 审批凭证。
- L1 缺 Issue 可继续，L2 Issue gate 必须继续 fail-closed，直到 V3 明确替代规则落地。

## 7. 当前 CI 基线

### 7.1 GitHub Actions

Workflow：`.github/workflows/workstation-test.yml`

触发路径：

- `scripts/ai/**`
- `scripts/env/**`
- `tests/workstation/**`
- `configs/ai/**`
- `Makefile`
- `.github/workflows/workstation-test.yml`

Workflow 步骤：

1. `actions/checkout@v4`
2. `actions/setup-python@v5` with Python 3.13
3. `python -m pip install --upgrade pip pytest`
4. `make workstation-doctor`
5. `python3 -m pytest -q tests/workstation`

最近 10 次 `workstation-test` 运行结论均为 `failure`。最新一次：

- Run id：`29247476110`
- Branch：`main`
- SHA：`06528f0efed48eff70285b5f299ca57945aa098f`
- 时间：2026-07-13
- 失败步骤：`make workstation-doctor`
- 日志摘要：`env_check` failed，`branch_not_main: current branch=main` failed，summary 为 `passed=10 failed=2 warn=2 skipped=2`

当前本地 HEAD `570dc665` 为文档更新，未出现在最新 workflow run 列表中；原因是 workflow paths 不包含普通文档路径。

### 7.2 本地测试

WS-GH-001 本地执行：

```bash
python3 -m pytest -q tests/workstation
```

结果：

```text
404 passed in 55.78s
```

```bash
bash -n scripts/ai/*.sh scripts/env/*.sh
```

结果：通过。

```bash
python3 scripts/ai/lib/schema_validator.py tests/workstation/fixtures/sample_task_v2.md
python3 scripts/ai/lib/schema_validator.py --epic tests/workstation/fixtures/sample_epic_v2.md
```

结果：通过。

```bash
git diff --check
```

结果：通过。

## 8. 当前 GitHub Issues / PR

查询时间：2026-07-14，本地通过 `gh` 只读查询。

Open PR：

- 无。

Open Issues：

| Issue | 标题 | Labels | 更新时间 | 分类 |
|---:|---|---|---|---|
| #12 | `TASK-2026-07-11-004: JM 实时 1m 真实 Gate（T1/T3）` | `type/task` | 2026-07-11 | active/stale candidate |
| #11 | `TASK-2026-07-11-003: Web 主图多指标切换（EMA overlay）` | `type/task` | 2026-07-11 | active/stale candidate |
| #10 | `TASK-2026-07-11-002: 火天大有指标与策略规范` | `type/task` | 2026-07-11 | active/stale candidate |
| #9 | `TASK-2026-07-11-001: 全量历史数据资产盘点（只读审计）` | `type/task` | 2026-07-11 | active/stale candidate |
| #8 | `GUIYI-DEMO-001: 为 GET /api/health 补充自动化测试` | none | 2026-07-11 | stale candidate |
| #7 | `[Demo] Lean V1 全链路验证 — TASK-2026-07-11-002-lean-v1-demo` | `status/delivery-ready` | 2026-07-11 | delivery-ready but open |
| #6 | `TASK-2026-07-11-001：归一量化单项目工作站精简收口与Demo前置修复（WORKSTATION-LEAN-V1-CLOSEOUT）：归一量化产品与交付工作站` | `type/task`, `status/delivery-ready` | 2026-07-11 | delivery-ready but open |

V3 前应先把 open Issues 做一次 triage：区分仍有效任务、历史 demo、应关闭项、应迁移到新 V3 flow 的任务。

## 9. 最近 commits

最近 10 个本地 commits：

```text
570dc665 (HEAD -> main, origin/main, origin/HEAD) 文档更新
ec7a698e 提交
e4bb6272 数据下载
55b94e20 Merge branch 'codex/data-stage-closure-doc-audit'
5fc08d21 (codex/data-stage-closure-doc-audit) chore(data): add data stage closure readonly audit package
5621ca54 Merge branch 'codex/data-layer-final-closure'
c9793d23 (origin/codex/data-layer-final-closure, codex/data-layer-final-closure) 提交
5b689c4d 下载内容
4229292e 下载
951aab41 修订
```

## 10. 本次不修改业务平面

WS-GH-001 不修改：

- `apps/**`
- `services/**`
- `packages/**`
- `strategies/**`
- `backtests/**`
- `scripts/**`
- `configs/**`
- `.github/**`
- `data/**`
- `logs/**`
- `output/**`
- `outputs/**`
- `.env*`
- PostgreSQL / Redis / DuckDB / Parquet / manifest / checksum / quality report

WS-GH-001 只新增：

- `docs/workstation/GITHUB_NATIVE_V3_BASELINE.md`

## 11. 后续 Step 冻结输入

建议后续按以下顺序推进，且每一步独立 TASK、独立 branch、独立 worktree、Draft PR：

1. `WS-GH-002`：文档协议对齐。修订 `AGENTS.md`、`CODEBUDDY.md`、`docs/workflows/github_issue_trace_workflow.md`、`docs/workstation/ARCHITECTURE.md`，引入 V3 四层事实模型和权限模型。
2. `WS-GH-003`：新增 PR template 和 GPT PR Review protocol。只改 `.github` 与 `docs/workflows`。
3. `WS-GH-004`：Issue-first bootstrap 设计与 dry-run。新增或扩展脚本以支持 `Issue #N -> TASK/branch/worktree` 的只读解析。
4. `WS-GH-005`：远程 task branch 接管。支持 GPT 已创建的 `task/<TASK_ID-slug>` 分支 fetch 与 worktree 创建。
5. `WS-GH-006`：Issue / PR 脱敏摘要回填。复用现有 `--confirm-issue-ops` 安全模型。
6. `WS-GH-007`：CI baseline 修复。解决 `workstation-test` 在 GitHub Actions `main` 上因 doctor strict `branch_not_main` 与 `env_check` 红灯的问题。
7. `WS-GH-008`：完整文档类 demo。用一个只改文档的任务验证 GPT Issue -> branch -> TASK -> Draft PR -> Codex plan/test/result -> GPT PR review。

任何后续 Step 均不得删除旧 `TASK_ID -> dispatch` 路径。

## 12. 验收状态

| 验收项 | 状态 |
|---|---|
| 无业务代码改动 | 通过 |
| 基线文档与实际仓库一致 | 通过，基于本地文件、`gh` 只读查询和本地测试 |
| 核心能力标记为复用 | 通过 |
| CI 基线明确记录 | 通过 |
| 当前 Issue / PR 状态明确记录 | 通过 |
| 后续 Step 输入明确 | 通过 |
