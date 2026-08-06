# Design Document: Personal Development Mode

## 1. Overview

本设计把仓库从“多人协作 + 多层审批 + worktree/PR 自动集成”收口为单一所有者的个人开发模式：普通仓库变更直接在 `develop` 编辑、验证、提交和推送；GitHub Issue、task branch/worktree、PR、独立 Review、required CI、exact-head、packet/hash/receipt 不再构成普通开发授权条件。

设计同时保留两类不可放宽的边界：

1. **业务正确性边界**：Historical Canonical、DatasetKey、DataGap、quality、策略/回测无未来函数、`Decimal`、SignalEvent 链路、默认关闭 live/Runtime/真实通知、禁止自动交易。
2. **真实外部副作用边界**：生产 DB/正式数据不可逆写入或删除、远端 release/tag、Git 历史重写、Runtime/live 切换、真实通知和 GitHub 规则修改，在执行前只要求一次包含操作类别与范围的明确意图；不再要求备份、packet、hash、exact-head、签名或第二次确认。

仓库主语言按现有源码构成确定为 **Python**。工程入口因 Windows 目标环境使用 **PowerShell 7**；应用与依赖分析仍复用 Python/pytest 生态，不引入 Bash、WSL、macOS 路径或 launchd 依赖。

本设计只描述后续实现，不表示当前 canonical、脚本、Runtime Gate 或任务合同已完成迁移。

## 2. Goals and Non-Goals

### 2.1 Goals

- 建立唯一普通开发流：`develop -> local validation -> commit -> push develop`。
- 让本地验证成为完成声明的依据，CI 仅作为可选补充。
- 让 canonical 文档、hooks/rules、工程脚本、workflow 和 active task contracts 同时收口，避免隐藏旧门禁。
- 用四个 PowerShell 7 原生入口替代 Bash/macOS/worktree/PR/release 多阶段工具。
- 普通删除直接依赖 Git 历史恢复，不创建备份、隔离副本、rollback tag 或删除 receipt。
- 对真实外部副作用保留一次、范围明确、单次消费的执行意图。
- 在清理 frozen/superseded Gate 代码前识别静态 import、动态 import、CLI 调用、配置引用和 Runtime 启动路径，避免删除后应用崩溃。

### 2.2 Non-Goals

- 不修改数据、策略、回测、信号或 HTDY 的业务语义。
- 不执行 migration、正式数据/DB 写入、Runtime/live 切换、真实通知、release、tag 或 GitHub ruleset 修改。
- 不恢复或扩展自动交易、订单提交或无人值守交易。
- 不为普通删除创建仓库内备份或额外归档。
- 不把 frozen historical 文档中的旧 PR、hash、packet、receipt 事实改写为当前授权规则。

## 3. Current-State Findings

当前实现存在以下直接冲突：

- `AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/DEVELOPMENT.md` 和 `docs/WORKTREE_RELEASE_WORKFLOW.md` 仍要求 task worktree、PR、CI、独立 Review、exact head 和 merge readback。
- `.codex/hooks/pre_tool_use_policy.py` 明确拒绝直接 push `develop`，`.codex/rules/workflow.rules` 将该操作标记为 forbidden。
- `scripts/engineering/preflight.sh --strict` 拒绝 `develop`；`task-worktree.sh`、`task_workflow.py`、`worktree_flow.py` 以 Issue/Lane/worktree/PR 为中心；`release-flow.sh` 要求 prepare/publish/tag 与多 SHA 绑定。
- `.github/workflows/lane-pr-gate.yml` 只服务 PR Gate；`engineering-test.yml` 仍调用 Bash/Makefile。
- `docs/tasks/GY-DATA-CORE-V2.md` 等 active 合同混合了业务安全约束、未来执行前置和已完成 PR/CI/Review 历史事实。
- frozen S6-10 代码不能按文件名直接删除。`services/quant-api/app/runtime_scheduler.py` 仍按 packet schema 动态导入 `htdy_s6_10_*_runtime_gate`，并直接类型检查 `HtDyS610LongRunningRuntimeGate`；直接删除会在启用相关路径时触发 `ImportError`，并可能让 Runtime 启动或调度失败。

## 4. Target Architecture

```text
Developer on develop
  -> Personal Preflight (read-only)
  -> Impact Classifier
  -> Local Validation Profiles
  -> Secret Scan
  -> git commit / git push origin develop

Optional GitHub CI
  -> invokes the same PowerShell validation contract
  -> publishes supplementary results only
  -> does not authorize local work, release, Runtime, or external writes

Controlled External Action
  -> normalize operation category + execution scope
  -> consume one explicit intent for one matching attempt
  -> enforce non-overridable business/safety constraints
  -> execute with fixed executable + argv
  -> report attempted scope and observed result
```

### 4.1 Components

#### Personal Workflow Policy

Pure policy layer that classifies:

- `Ordinary_Repository_Change`
- `Ordinary_Repository_Deletion`
- `Controlled_External_Action`
- `Business_Correctness_Constraint`

The policy does not classify paths into Lane 1/2/3 and does not inspect Issue, PR, Review, CI or exact-head state. It only selects validation and determines whether an operation crosses the repository boundary.

#### Impact Classifier

Maps changed paths to validation domains:

- `docs`
- `engineering`
- `backend`
- `web`
- `data-core`
- `strategy-backtest-signal`
- `runtime-live-notification`
- `migration`

The classifier selects tests; it does not authorize code changes or external mutation.

#### PowerShell Engineering Entry Points

Four active scripts under `scripts/engineering/`:

- `preflight.ps1`
- `validate.ps1`
- `secret-scan.ps1`
- `release-tag.ps1`

All scripts:

- require PowerShell 7;
- resolve the repository root through `git rev-parse --show-toplevel`;
- invoke fixed executables with discrete argument arrays;
- reject unknown options and malformed paths;
- return `0` on success, `1` for validation/operation failure, and `2` for invalid invocation;
- support `-Json` with a stable bounded result schema;
- avoid printing environment values, remote credentials or matched secret text.

#### Repository Consistency Checker

A Python module invoked by `validate.ps1 -Profile Engineering` that inventories active surfaces and reports residual collaboration blockers. The checker uses a context-aware allowlist/denylist rather than banning words globally: `hash`, `receipt`, `Review` and `PR` may remain inside Historical_Fact passages or data-integrity contracts, but cannot remain as authorization predicates for ordinary code work.

#### Runtime Dependency Inventory

A Python scanner and explicit disposition manifest used only during Gate cleanup. It discovers:

1. Python `import` / `from` edges with AST parsing.
2. Dynamic import edges (`importlib`, string module names).
3. CLI/subprocess references to scripts.
4. Configuration/env/service-template references.
5. FastAPI startup, queue worker, scheduler and health call paths.
6. Tests and docs references, reported separately from Runtime references.

A candidate is deletable only after active Runtime/code references are zero and replacement startup/scheduler tests pass.

## 5. Personal Development Workflow

### 5.1 Ordinary Change State Model

```text
START
  -> inspect branch/status/recent commits
  -> branch == develop ? continue : optional user-selected workflow
  -> preserve unrelated dirty paths
  -> edit only task scope
  -> classify impact
  -> run selected local validation
  -> run secret scan when tracked content changes
  -> validation passed ? completion allowed : report failure
  -> optional commit
  -> optional direct push origin develop
END
```

A dirty worktree is not an automatic failure. Preflight reports dirty paths without content. The implementation must compare the before/after path set and prevent automation from staging or modifying unrelated paths. Automated commit helpers, if any, stage explicit paths only; `git add .` and `git add -A` are not part of the canonical flow.

### 5.2 Optional Collaboration Tools

Branch, worktree, PR, Review and CI remain usable when the developer chooses them, but no active policy may require their metadata. Optional use must not change the result of local validation or grant authority for an external side effect.

### 5.3 Ordinary Deletion

Repository-local deletion follows:

```text
classify as repository-local
-> scan active references
-> remove target and active references in one change
-> run affected tests + consistency scan
-> commit deletion
-> recover from Git history if needed
```

No backup directory, quarantine, archive copy, deletion packet, rollback tag or receipt is created. Uncommitted deletion is recoverable with normal Git restore; committed deletion is recoverable from the parent commit or a revert.

Deletion becomes a `Controlled_External_Action` when the target is a production DB row, formal market data outside Git, Runtime state, remote ref, Git history, live configuration, notification channel or another external resource.

## 6. Controlled External Action Design

### 6.1 Intent Model

```python
from dataclasses import dataclass
from enum import StrEnum

class OperationCategory(StrEnum):
    RELEASE_BRANCH = "release_branch"
    PUSH_TAG = "push_tag"
    FORCE_UPDATE = "force_update"
    PRODUCTION_DATA_WRITE = "production_data_write"
    PRODUCTION_DELETE = "production_delete"
    RUNTIME_SWITCH = "runtime_switch"
    LIVE_ENABLE = "live_enable"
    REAL_NOTIFICATION = "real_notification"
    GITHUB_RULE_CHANGE = "github_rule_change"

@dataclass(frozen=True)
class ExecutionScope:
    category: OperationCategory
    environment: str
    target: str
    resource_boundary: tuple[str, ...]

@dataclass
class ExplicitIntent:
    scope: ExecutionScope
    consumed: bool = False
```

The direct user request is the intent. The implementation does not persist the intent to disk and does not derive reusable authorization from a dry-run. One intent can authorize one immediately following matching attempt; success, failure, scope change, retry or later session requires a new request.

### 6.2 Precedence

```text
Business_Correctness_Constraint
  > input/scope validation
  > explicit intent
  > operation execution
```

Explicit intent cannot enable automatic trading, bypass failed data quality, allow future-data leakage, expose secrets, turn on default autosend, or permit out-of-scope resources.

### 6.3 Reporting

Execution output reports only:

- operation category;
- normalized non-secret scope;
- attempted/not-attempted;
- success/failed/blocked;
- bounded error type;
- remote/ref/commit for release/tag where applicable.

No final receipt artifact is required or generated.

## 7. PowerShell Command Interfaces

### 7.1 Preflight

```powershell
pwsh -NoProfile -File .\scripts\engineering\preflight.ps1 [-Json] [-RequireClean]
```

Default checks are read-only and permit `develop`:

- Git and PowerShell versions;
- repository root;
- branch name;
- changed path summary;
- Python, `uv`, Node and package-manager availability;
- optional data path presence without creating directories;
- count of secret-like environment variable names without values.

`-RequireClean` is an explicit operation-specific constraint for release/tag and similar exact Git operations; it is not used by ordinary development.

### 7.2 Validation

```powershell
pwsh -NoProfile -File .\scripts\engineering\validate.ps1 `
  -Profile Engineering|Docs|Backend|Web|DataCore|Strategy|Runtime|AllSafe `
  [-TestPath <repo-relative-path> ...] [-Json]
```

Rules:

- profile is a closed enum;
- `-TestPath` accepts only normalized paths under approved test roots and approved extensions;
- child commands are fixed argv arrays, never `Invoke-Expression`, `cmd /c`, `powershell -Command <user text>` or interpolated shell strings;
- multiple child failures aggregate to non-zero;
- missing tools produce a bounded `unavailable` result and a configured alternative, not a false pass;
- domain profiles preserve existing business-specific tests.

Canonical direct commands remain documented for specialized suites, for example `uv run ... pytest`, `uv run ... ruff`, and `pnpm --dir ... test/build`. The wrapper does not accept arbitrary command text.

### 7.3 Secret Scan

```powershell
pwsh -NoProfile -File .\scripts\engineering\secret-scan.ps1 `
  [-Path <repo-relative-path> ...] [-WarnOnly] [-Json]
```

The scanner ports the current high-confidence pattern families and exclusions. Input paths are canonicalized and must remain below the repository root. Output contains only path, line number and pattern family. Default is fail-closed; optional CI never uses `-WarnOnly`.

### 7.4 Release and Tag

```powershell
# Publish selected local commit to a release branch
pwsh -NoProfile -File .\scripts\engineering\release-tag.ps1 `
  -Operation PublishBranch -Remote origin -SourceRef develop -TargetBranch main [-WhatIf] [-Json]

# Create and push one annotated tag
pwsh -NoProfile -File .\scripts\engineering\release-tag.ps1 `
  -Operation PublishTag -Remote origin -SourceRef develop `
  -TagName v1.2.3 -Message "release v1.2.3" [-WhatIf] [-Json]
```

`-WhatIf` is optional and never authorizes mutation. A mutating invocation is itself the execution attempt after the user has supplied explicit scope in the request. The script prints remote, target ref/tag and resolved local commit before the first mutation, then:

- validates remote and Git ref names with Git;
- requires a clean release working tree;
- fetches/read-checks the target remote ref;
- permits branch publication only as fast-forward;
- rejects conflicting tags;
- never adds force flags;
- does not update Runtime/live/notification state;
- does not create rollback tags or backups.

Force-push/history rewrite is not a switch on this command. It is a separate controlled operation and remains unavailable until separately designed and explicitly requested.

## 8. File-Level Change Matrix

| Area | File(s) | Target action | Compatibility / acceptance |
|---|---|---|---|
| Root execution rule | `AGENTS.md` | Rewrite ordinary flow to direct `develop`; retain security, data, strategy, Runtime/live/notification boundaries | Must contain one authoritative workflow and no task→PR Gate requirement |
| Current status | `STATUS.md` | Update only current migration/Gate statements made factually obsolete; preserve completed execution facts | No claim that external operations were rerun |
| Long-term source | `PROJECT_SOURCE.md` | Replace worktree lifecycle with personal mode; retain product/data boundaries | Module responsibility points to personal workflow canonical |
| Long-term decisions | `DECISIONS.md` | Add personal-mode decision; remove ADR-WS-003/004 from active ADR list; replace packet/hash authorization decision with scoped intent | Completed packet/hash facts remain facts, not active rules |
| Development canonical | `docs/DEVELOPMENT.md` | Rewrite as concise direct-develop workflow, impact validation, external-action boundary | No Lane/Issue/worktree/PR/Review/exact-head prerequisite |
| Workflow canonical | `docs/WORKTREE_RELEASE_WORKFLOW.md` | Replace with `docs/PERSONAL_DEVELOPMENT_WORKFLOW.md`; delete old filename after all active references are changed | Git history retains old workflow; one active canonical path remains |
| Old ADRs | `docs/decisions/ADR-WS-003-*.md`, `ADR-WS-004-*.md` | Delete from active tree | `DECISIONS.md` records supersession; historical text remains in Git |
| Testing docs | `TESTING.md` | Replace Bash/Make commands with canonical PowerShell and direct Python/Node commands; remove exact-head/read-only approval wording that is only collaboration authorization | Keep domain test semantics and actual historical results clearly labeled |
| README | `README.md` | Update Windows entrypoints and scoped-intent boundary | Preserve observation-only/no-order statement |
| Make wrapper | `Makefile` | Delete as active engineering entrypoint, unless retained solely as clearly optional non-Windows convenience with no canonical references | Windows commands cannot depend on `make` |
| Codex config | `.codex/config.toml` | Remove project hook registration if hook becomes empty; otherwise point only to retained non-collaboration safety hook using available Windows Python | No `/usr/bin/python3` or Bash-only command |
| Codex hook | `.codex/hooks/pre_tool_use_policy.py` | Remove direct-develop/push, merge/rebase and worktree-flow collaboration blocks; retain only destructive Git protections if not already enforced globally | Direct `git push origin develop` is not denied solely by branch |
| Codex rules | `.codex/rules/workflow.rules` | Delete task-worktree allow rules and develop forbidden rule; retain narrow force-push/history-rewrite protection or delete file if redundant | No collaboration entrypoint remains |
| Preflight | `scripts/engineering/preflight.sh` -> `preflight.ps1` | Replace | `develop` passes; dirty paths warn by default; Windows paths supported |
| Validation | `scripts/engineering/test.sh` -> `validate.ps1` | Replace | Fixed profiles and domain-specific suites preserved |
| Secret scan | `scripts/engineering/check-secrets.sh` -> `secret-scan.ps1` | Replace | Pattern families/output secrecy preserved |
| Release | `scripts/engineering/release-flow.sh` -> `release-tag.ps1` | Replace three-stage flow with single branch/tag operations | No prepare/publish split, rollback tag, packet/hash/exact-head arguments |
| Worktree orchestration | `task-worktree.sh`, `task_workflow.py`, `worktree_flow.py` | Delete | All active callers/tests/docs removed in same migration |
| Generic Runtime promotion | `runtime-promotion.sh` | Delete as collaboration/hash wrapper | Runtime switching remains separate controlled action in domain code, default disabled |
| Runtime health | `runtime-health.sh` | Remove from active engineering set; use `uv run --project services/quant-api guiyi runtime status` or port a Runtime-specific PowerShell wrapper only if still needed | Never an ordinary development prerequisite |
| Engineering tests | `tests/engineering/test_codex_automation_policy.py` | Replace old Lane/hook/PR tests with personal policy, consistency and intent tests | Historical workflow behavior no longer tested as active |
| Entrypoint tests | `tests/engineering/test_engineering_entrypoints.py` | Port subprocess tests to `pwsh`; add Windows path, exit-code and local bare-remote tests | Tests run without Bash |
| GitHub PR Gate | `.github/workflows/lane-pr-gate.yml` | Delete | No PR-only required check remains in repository |
| Optional CI | `.github/workflows/engineering-test.yml` | Rename/rewrite to `optional-ci.yml`, use `pwsh`, `uv`, Node; trigger by `workflow_dispatch` and optionally push to `develop` | Result is supplementary; repository ruleset changes require separate explicit intent |
| Task index | `docs/tasks/README.md` | Replace Gate/hash-path retention policy with active/frozen/historical classification | Runtime-consumed files remain until call sites migrate |
| Active data contract | `docs/tasks/GY-DATA-CORE-V2.md` | Remove future Issue/worktree/PR/Review/CI/exact-head/packet/receipt prerequisites; keep canonical/data/live safety and completed facts | Completed PR/CI/Review/SHA passages stay historical or are removed with Git history available |
| Product retirement | `docs/tasks/GY-DATA-PRODUCT-RETIREMENT-21.md` | Replace collaboration and backup/packet authorization prerequisites with one scoped deletion intent; retain exact product matching, blockers, transactional/data-integrity checks and default disabled state | Existing measured counts and incident facts remain historical facts |
| Future Runtime acceptance | retired | Old acceptance contracts are Git-only; any future Runtime validation starts as a new task | Release and Runtime still require separate scoped intents |
| Frozen S6 docs | `S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md` | Keep only the still-consumed recovery contract; S6-08/S6-10 contracts are Git-only | Active Runtime bindings were removed before deletion |
| Legacy task snapshots | `GY-CORE-01-*`, `GY-CORE-02-*`, `GY-CORE-CONVERGENCE.md`, completed approval/evidence docs | Delete when not Runtime/code referenced, or retain explicitly as historical with no active authorization | Recovery is Git history; no archive copy |
| Runtime scheduler | retired | The old scheduler and plan CLI are removed; after-market scheduling remains separate and default-off | Runtime status stays read-only |
| Frozen Gate modules/scripts/tests | `app/services/htdy_s6_10_*`, `scripts/jm_htdy_s6_10_*`, corresponding tests | Delete in dependency-ordered batches only after zero active references | No direct bulk deletion |

## 9. Task Contract Migration Model

Every file in `docs/tasks/` receives one disposition in a machine-readable in-memory inventory produced by the consistency checker; no new permanent receipt is created.

| Class | Meaning | Migration rule |
|---|---|---|
| `active_contract` | Still defines future work or an active business boundary | Remove collaboration authorization predicates; retain business correctness and one scoped-intent boundary |
| `historical_fact` | Records completed execution, incident or observed evidence | Preserve wording or delete file and rely on Git; never reinterpret as current authorization |
| `frozen_runtime_consumed` | Frozen text/file still read, hashed, imported or referenced by Runtime | Retain until caller/config migration and runtime smoke pass |
| `superseded_unreferenced` | No active caller and no current business boundary | Delete with active references in one commit; Git is recovery source |

Context-aware clause handling:

- Remove: “must have Issue”, “task worktree clean”, “PR/independent Review/required CI/exact head before code integration”, “approval packet/hash/signature/receipt authorizes execution”.
- Retain: file checksum, manifest digest, data fingerprint, idempotency key, canonical identity, quality proof, transactional blocker, historical statement that a prior PR/packet/receipt existed.
- Rewrite: future real operation authorization becomes “one explicit request naming operation category and scope”; safety preconditions remain normal code validation rather than approval artifacts.

## 10. Safe Removal of Frozen/Superseded Gate Code

### 10.1 Reference Classification

For every candidate module/script/document, the inventory emits:

```python
from dataclasses import dataclass
from enum import StrEnum

class ReferenceKind(StrEnum):
    RUNTIME_IMPORT = "runtime_import"
    DYNAMIC_IMPORT = "dynamic_import"
    CLI_CALL = "cli_call"
    CONFIG_REFERENCE = "config_reference"
    TEST_ONLY = "test_only"
    DOC_ONLY = "doc_only"

@dataclass(frozen=True)
class RemovalCandidate:
    path: str
    references: tuple[tuple[str, ReferenceKind], ...]
    replacement: str | None
    disposition: str  # retain, migrate_then_delete, delete
```

A candidate with `RUNTIME_IMPORT`, `DYNAMIC_IMPORT`, `CLI_CALL` or `CONFIG_REFERENCE` cannot be marked `delete`.

### 10.2 Runtime Migration Sequence

1. Freeze the deletion candidate list; do not delete files yet.
2. Scan AST, string imports, subprocess calls, env/config keys, service templates and entrypoint registration.
3. Trace Runtime startup roots: FastAPI app import, scheduler main, queue workers, CLI runtime commands and health routes.
4. Change callers first. For current S6-10 schemas 4/5/6/7 and Approval D packet types, return a bounded `superseded_runtime_gate_disabled` error before importing old modules.
5. Keep live, signal write, Runtime switch and autosend defaults false during and after migration.
6. Run import, startup, disabled scheduler, CLI help, health and targeted Runtime tests.
7. Re-run the reference inventory. Only candidates with zero active references may be deleted; test/doc references are removed in the same change.
8. Run the same smoke tests after deletion.

This sequence avoids replacing a safe fail-closed Gate with `ImportError`, partial startup or an accidentally unguarded path.

### 10.3 Compatibility Strategy

- **No active authorization compatibility**: old packet/hash/signature mechanics do not remain valid execution authorization.
- **Read-only historical compatibility**: parsers may retain enough schema recognition to return `superseded_runtime_gate_disabled` without importing old execution modules.
- **Configuration compatibility**: old env/config keys are accepted only to fail closed with a bounded migration error; absent or malformed values keep features disabled.
- **Data compatibility**: existing DB rows, SignalEvent history, ledgers and historical reports are not rewritten by this workflow migration.
- **API compatibility**: Runtime health remains available through the existing application CLI/API; engineering script deletion does not remove application health contracts.

## 11. Optional CI Design

`optional-ci.yml` uses `windows-latest` for the engineering entrypoint contract and may use additional Linux jobs only for application suites that are already cross-platform. The canonical job invokes:

```powershell
pwsh -NoProfile -File .\scripts\engineering\preflight.ps1 -Json
pwsh -NoProfile -File .\scripts\engineering\validate.ps1 -Profile Engineering -Json
pwsh -NoProfile -File .\scripts\engineering\secret-scan.ps1 -Json
```

CI is not referenced by local policy, release/tag authorization, cleanup or completion claims. If a GitHub ruleset currently requires old checks, changing that ruleset is a separate `Controlled_External_Action`; repository file changes alone must not claim the remote rule has changed.

## 12. Data Models and Stable Result Schema

All PowerShell tools return the same top-level JSON shape when `-Json` is selected:

```json
{
  "schema_version": 1,
  "tool": "scripts/engineering/validate.ps1",
  "operation": "validate",
  "mode": "read_only",
  "status": "ok",
  "summary": {"passed": 3, "failed": 0, "warn": 1, "unavailable": 0},
  "checks": [
    {"name": "example", "status": "passed", "detail": "bounded non-secret detail"}
  ]
}
```

Allowed statuses are `ok`, `failed`, `blocked`, and `unavailable`. Check status is `passed`, `failed`, `warn`, or `unavailable`. Unknown status values fail tests.

Release/tag results additionally contain a bounded `scope` object with remote, target ref/tag and resolved commit. They never include remote URLs containing credentials, environment values, packet paths, approval hashes or secret-bearing command lines.

## 13. Error Handling and Security

- Unknown parameters, invalid enum values, malformed refs and paths outside the repository return exit `2` before side effects.
- Child validation failures return exit `1`; a successful subset cannot mask another failure.
- Git conflicts, non-fast-forward updates and tag collisions return bounded errors and never trigger force behavior.
- PowerShell uses the call operator with argument arrays; no `Invoke-Expression` or user-composed shell command.
- File paths are normalized with .NET APIs, checked against the allowed root, and passed as one argument.
- Secret scanning reads bounded files, skips explicit binary/generated classes, and never prints the match.
- External errors are truncated and redacted before user/API boundaries.
- Missing quality/safety/live/Runtime/notification configuration fails closed.
- No workflow simplification may alter SQL parameterization, URL safety, upload handling, authentication, data quality, strategy semantics or notification defaults.

## 14. Migration Phases

### Phase A — Establish Personal Canonical

- Rewrite canonical documents in one consistency change.
- Record ADR-WS-003/004 supersession in `DECISIONS.md`, delete both ADR files, and replace the worktree workflow canonical.
- Do not yet delete Runtime-consumed frozen files.

Acceptance: no active canonical says ordinary work cannot occur on `develop`; business boundaries are unchanged.

### Phase B — Add Windows-Native Entry Points

- Add four PowerShell scripts and their pytest subprocess tests.
- Update `TESTING.md`/README and optional CI to use the same commands.
- Validate spaces, Unicode, Windows separators, exit codes and secret redaction.

Acceptance: documented commands run on Windows without Bash/WSL/make.

### Phase C — Remove Collaboration Enforcement

- Simplify/delete `.codex` hook/rules.
- Delete task worktree/Lane/PR tooling and old tests.
- Delete `lane-pr-gate.yml`; keep only optional CI.

Acceptance: direct ordinary commit/push on `develop` is not blocked solely because Issue/worktree/PR/Review/CI/exact-head evidence is absent.

### Phase D — Migrate Active Task Contracts

- Classify every `docs/tasks/` file.
- Rewrite active contracts, preserve or Git-delete historical facts, and retain Runtime-consumed frozen files.
- Run context-aware consistency scans.

Acceptance: active code-only work has no collaboration prerequisite; domain safety remains.

### Phase E — Decouple and Remove Frozen Gate Code

- Produce the Runtime dependency inventory.
- Rewrite Runtime callers/config first to deterministic superseded errors.
- Delete zero-reference Gate modules/scripts/tests in small batches.

Acceptance: FastAPI import/startup, scheduler-disabled, CLI runtime status and health tests pass before and after deletion; live/Runtime/notification remain disabled.

### Phase F — Final Consistency and Optional Remote Follow-Up

- Run full local validation, secret scan and active-reference scans.
- If GitHub required checks/rules still enforce old CI, report remote migration incomplete; modify remote rules only after a separate explicit scoped request.

Acceptance: every requirement criterion has a mapped test/static check/manual external-status result.

## 15. Rollback Strategy

Rollback uses Git only:

- before commit: `git restore` selected paths;
- after commit but before push: revert or reset through normal user-selected Git action;
- after shared push: create a normal revert commit on `develop`;
- deleted files: restore from the parent commit or revert the deletion commit.

The migration does not create backup directories, tarballs, quarantine trees, rollback tags, packet snapshots or receipt artifacts. Runtime/data/DB external mutations are outside this repository migration; this design does not execute them. A release/tag conflict is reported rather than “rolled back” through an automatically created tag.

## 16. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Canonical documents disagree during migration | Phase A updates all active canonical references together; consistency checker blocks completion on residual direct-develop blockers |
| Direct `develop` work overwrites unrelated changes | Record initial path set, edit/stage explicit paths, property-test disjoint dirty sets |
| Removing hook also removes useful Git safety | Retain narrow force-push/history-rewrite protections; remove only collaboration-specific blocks |
| PowerShell quoting introduces injection/path bugs | Closed enums, normalized containment, fixed executable + argv, generated Unicode/metacharacter tests |
| Optional CI is still remotely required | Report remote rules separately; change rules only under explicit scoped intent |
| Contract cleanup removes historical meaning | Classify clauses; preserve text or rely on immutable Git history; do not rewrite completed outcomes |
| Blanket Gate deletion breaks Runtime | Caller-first migration, static/dynamic reference inventory, bounded superseded adapter, pre/post deletion startup tests |
| Removing packet/hash checks weakens business correctness | Keep checksums/digests/quality/transactional invariants as validation, remove only their role as human authorization artifacts |
| Simplified release overwrites remote history | Fast-forward only, no force switch, explicit remote/ref/commit display, local bare-remote integration tests |
| Ordinary deletion is misclassified as external deletion | Resource classifier treats DB/data/Runtime/remote refs/Git history as controlled by construction |
| Workflow changes accidentally enable live or notification | Default-off property tests and Runtime disabled smoke are mandatory in every relevant phase |

## 17. Correctness Properties

Property reflection consolidated overlapping criteria into the smallest set that still provides distinct validation value. In particular, ordinary-develop authorization is one property rather than separate Issue/PR/Review properties; one-shot intent combines scope, consumption and dry-run behavior; and default-off behavior combines live, Runtime, notification and orders.

### Property 1: Ordinary develop authorization is collaboration-invariant

For any `Ordinary_Repository_Change` path set on `develop`, and for any presence or absence of Issue, task branch, worktree, PR, Review, CI, exact-head, merge-readback or cleanup metadata, local editing and validation authorization is unchanged and does not require a Collaboration_Gate.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2**

### Property 2: Unrelated dirty changes are preserved

For any two disjoint path sets representing pre-existing changes and current-task changes, every personal-workflow operation changes or stages only the current-task set and leaves the content and index state of the pre-existing set unchanged.

**Validates: Requirements 1.8**

### Property 3: Residual collaboration blockers fail consistency

For any active canonical, hook, rule, engineering script, workflow or active code-only task-contract clause, adding a rule that rejects ordinary `develop` work solely because an old collaboration prerequisite is absent causes the repository consistency result to be `incomplete`.

**Validates: Requirements 2.8, 12.6, 12.7, 12.8**

### Property 4: Explicit intent is scoped, one-shot and non-persistent

For any Controlled_External_Action and normalized Execution_Scope, a matching Explicit_Execution_Intent authorizes at most the immediately following matching attempt; missing scope, missing intent, an out-of-scope target, a retry, a changed scope, a later session or a dry-run produces zero unauthorized mutations.

**Validates: Requirements 2.3, 5.1, 5.2, 5.3, 5.5, 5.6, 5.8**

### Property 5: External result reporting is bounded and receipt-free

For any successful, failed or blocked Controlled_External_Action attempt, the result contains the attempted category, normalized non-secret scope and observed status, and does not require or create a final receipt artifact.

**Validates: Requirements 5.7**

### Property 6: Business constraints dominate intent

For any Explicit_Execution_Intent paired with a violated Business_Correctness_Constraint, the sensitive operation is rejected; release/tag intent grants no Runtime, live, notification, data-quality bypass or order capability.

**Validates: Requirements 5.9, 6.8, 11.5**

### Property 7: Validation profile matches impact

For any changed path set, the selected Validation_Profile includes every affected executable/domain suite, selects only applicable document checks for docs-only changes, and includes data/strategy/backtest/signal/migration/Runtime/notification suites when those domains are affected.

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 8: Validation and command exit codes are truthful

For any set of child validation outcomes, any required failure yields a non-zero result and no successful completion claim, while all successful required checks yield exit code zero; an unavailable Windows tool is reported as unavailable with the closest configured alternative rather than as passed.

**Validates: Requirements 3.4, 3.7, 7.4, 7.5**

### Property 9: Repository deletion classification and reference closure

For any deletion target, repository-local tracked source/test/config/doc/workflow assets are classified as Ordinary_Repository_Deletion, production DB/formal data/Runtime/remote-ref/Git-history targets are classified as Controlled_External_Action, and completion of a repository deletion leaves zero unresolved active references to the deleted asset.

**Validates: Requirements 4.1, 4.2, 4.3, 4.5**

### Property 10: Active Runtime references prevent deletion

For any frozen or superseded Gate candidate, the presence of a Runtime import, dynamic import, CLI call or configuration reference prevents a `delete` disposition; deletion becomes eligible only after active references are zero and replacement startup/scheduler checks pass.

**Validates: Requirements 4.3, 12.3**

### Property 11: Release/tag mutation validates and announces its exact target

For any release/tag input, the command emits remote, target branch or tag, and resolved local commit before the first mutation; invalid/unavailable refs or tag names produce zero mutation calls, and a force update requires a different operation category and intent.

**Validates: Requirements 6.4, 6.5, 6.7**

### Property 12: Paths and command arguments cannot escape their boundary

For any path or argument containing spaces, non-ASCII characters, Windows separators or shell metacharacters, engineering tools pass the value as one discrete argument; file operations accept the path only when normalized resolution remains under the allowed root.

**Validates: Requirements 7.3, 8.3, 8.5**

### Property 13: Secrets are detected without disclosure

For any generated credential, token, webhook, password, cookie, license or private-key fixture matching a supported family, the secret scan fails closed and reports only file path, line and pattern family; logs and bounded errors exclude the matched value and internal sensitive details.

**Validates: Requirements 8.1, 8.6, 8.8**

### Property 14: Invalid external input fails before sensitive operations

For any malformed type, format, range, allowed value, associated field, authentication state, quality state or safety flag, validation rejects the input before invoking a command, database, file mutation, network mutation or other sensitive mock.

**Validates: Requirements 8.2, 8.7**

### Property 15: Formal historical requests preserve explicit identity and quality

For any formal historical request, the consumer supplies a complete DatasetKey and an explicit `continuous` or `actual_dominant` kind, uses MarketDataService or the active canonical interface, rejects DataGap/failed-quality intersections without fallback, accepts only `passed` for strict research, and applies exactly the legacy compatibility predicate where legacy mode remains.

**Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.6**

### Property 16: Historical and live data remain separated and publication is atomic

For any Live_Observation or failed staging/canonical validation result, no live value is promoted to Historical_Canonical and the last valid Historical_Canonical identity and content remain unchanged.

**Validates: Requirements 9.7, 9.9**

### Property 17: Formal data mutation requires matching scoped intent

For any irreversible formal-data or production-database mutation scope, zero writes occur without a matching one-shot Explicit_Execution_Intent.

**Validates: Requirements 9.10**

### Property 18: Strategy outputs are prefix-causal

For any valid market-data prefix and any appended future suffix, strategy, backtest and formal historical signal outputs for times inside the prefix remain unchanged, except for the explicitly recorded HTDY observation-only repainting semantics.

**Validates: Requirements 10.2**

### Property 19: Trading numerical values preserve Decimal semantics

For any valid prices, costs, positions, capital, profit, loss and fees, trading-related calculations accept and produce `Decimal` domain values without introducing binary floating-point arithmetic.

**Validates: Requirements 10.3**

### Property 20: HTDY original is accepted only by the observation whitelist

For any consumer and execution context, HTDY original behavior is accepted if and only if the context matches the canonical realtime first-seen observation-only whitelist; formal backtest, historical validation, autosend and trading contexts are rejected.

**Validates: Requirements 10.5**

### Property 21: Research outputs cannot become order instructions

For any signal or backtest presentation, output includes the research-observation/non-trading-instruction boundary; for any requested workflow that would create or submit an order, the workflow is rejected before an order adapter is invoked.

**Validates: Requirements 10.7, 10.8**

### Property 22: Semantic changes require their canonical companion

For any diff that changes data, strategy, backtest, signal or notification semantics, the required corresponding deep canonical path is included in the same change.

**Validates: Requirements 10.9**

### Property 23: Operational capabilities default closed

For any absent, default, malformed, expired or inconsistent configuration, live execution, Runtime promotion/switching, real notification/autosend and order placement remain disabled, and every signal/Runtime mode has `auto_order=false`.

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.7, 12.9**

### Property 24: Historical processing cannot dispatch notifications

For any repair, replay, backfill, migration or EOD recalculation context, the real notification dispatcher receives zero calls.

**Validates: Requirements 11.6**

### Property 25: Real notification output remains observation-only

For any real notification payload, the message contains the observation-only and non-trading-instruction boundary; for any successful or failed live/Runtime/notification execution result, trading, profitability, long-running and production readiness are not inferred.

**Validates: Requirements 11.8, 11.9**

### Property 26: Acceptance coverage is complete and safety-sensitive

For all acceptance-criterion identifiers in `requirements.md`, the final verification matrix contains at least one mapped test or static/integration check; any witness showing accepted invalid input, failed data quality, DataGap fallback, future leakage or secret exposure makes overall acceptance fail.

**Validates: Requirements 12.10, 12.12**

## 18. Testing Strategy

### 18.1 Unit and Property Tests

- Use pytest for policy, classifier, dependency-inventory and subprocess assertions.
- Use Hypothesis only if already available or after verifying the official package and pinning an exact version; otherwise implement deterministic parameterized generators with the existing test stack.
- Each property test runs at least 100 generated cases and includes the tag `Feature: personal-development-mode, Property N: <title>`.
- Unit tests cover fixed examples: no Issue/PR context, bounded superseded schema error, exact help text, malformed CLI, historical fact preservation and dry-run behavior.

### 18.2 PowerShell Integration Tests

Run `pwsh -NoProfile -File` from Python subprocess tests against temporary repositories and local bare remotes:

- direct `develop` preflight;
- dirty unrelated paths;
- spaces, Chinese characters and metacharacters in paths;
- fixed validation profiles and child failure propagation;
- secret detection/redaction;
- fast-forward branch publish;
- annotated tag publish;
- non-fast-forward and conflicting tag rejection;
- no force flag and no rollback tag creation.

### 18.3 Runtime Safety Tests

Retained Runtime safety checks cover:

- import `app.main` and the retained runtime health/after-market modules;
- FastAPI startup/lifespan smoke with external services mocked;
- signal/live/notification flags disabled;
- `guiyi runtime status` help/read-only path;
- Runtime health contract;
- no SignalEvent, notification, order or Runtime mutation calls.

### 18.4 Domain Regression

Retain existing targeted suites for:

- data-core DatasetKey/Catalog/Manifest/Gap/MainContractMap/MarketDataService;
- strategy/backtest/signal causal and Decimal contracts;
- migration isolation;
- Runtime/live/notification default-off behavior;
- secret and input validation.

### 18.5 Static Consistency Checks

- every active canonical uses the personal workflow;
- no active ordinary-development clause requires old collaboration artifacts;
- ADR-WS-003/004 and old workflow path have no active references;
- deleted scripts/modules have zero active references;
- all documented engineering commands start with `pwsh` or direct project-native Python/Node commands;
- retained non-Windows Runtime commands are explicitly optional/Runtime-specific;
- every requirements criterion maps to a verification result.

## 19. Acceptance Mapping

| Requirement group | Primary design sections | Primary verification |
|---|---|---|
| 1 Direct develop | 4, 5 | Properties 1–2; temporary Git repository tests |
| 2 Gate removal | 5, 8, 9 | Properties 1, 3–4; consistency scan |
| 3 Validation | 4, 7 | Properties 7–8; PowerShell subprocess tests |
| 4 Deletion | 5.3, 8, 15 | Properties 9–10; Git restore/revert integration |
| 5 Explicit intent | 6 | Properties 4–6; one-shot state tests |
| 6 Release/tag | 7.4 | Properties 6, 11; local bare-remote integration |
| 7 Windows/pwsh | 7, 11 | Properties 8, 12; windows-latest and local pwsh tests |
| 8 Security | 7.2–7.4, 13 | Properties 12–14; secret/input/error tests |
| 9 Data boundaries | 2, 10.3, 18.4 | Properties 15–17; existing data-core suites |
| 10 Strategy/backtest/signal | 2, 18.4 | Properties 18–22; causal/Decimal/domain tests |
| 11 Live/Runtime/notification | 6.2, 10, 18.3 | Properties 6, 23–25; disabled smoke |
| 12 Consistency/acceptance | 8, 9, 14, 18.5 | Properties 3, 10, 23, 26; full traceability matrix |
