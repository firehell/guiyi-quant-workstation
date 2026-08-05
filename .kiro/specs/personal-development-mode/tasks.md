# Implementation Plan: Personal Development Mode

## Overview

本计划按设计的 Phase A–F 将仓库迁移为个人开发模式。执行顺序坚持：先统一 canonical，再建立 PowerShell 7 原生入口，随后移除协作门禁、迁移 active task contracts，最后按 caller-first 原则去耦并删除零 active reference 的 frozen Gate 资产。

所有任务均为仓库内代码、测试或文档修改及其自动化验证。任务执行期间允许按本 Spec 直接在当前 `develop` 工作区修改，但不得自动 commit/push。任何真实 release/tag、GitHub rules 修改、生产 DB/正式数据写入、Runtime/live 切换、真实通知或自动交易均不在任务授权范围内；release/tag 测试只允许使用临时本地 Git 仓库与本地 bare remote。

本地 Windows 环境可能缺少完整 Python/uv；实现侧以仓库文件变更为准，验证可在 Mac Mini 宿主执行。

## Tasks

- [x] 1. Phase A — Establish Personal Canonical
  - [x] 1.1–1.3 Canonical rewrite, workflow replacement, consistency tests
  - [x] 1.4 Checkpoint (deferred host validation)

- [x] 2. Phase B — Add Windows-Native Engineering Entry Points
  - [x] 2.1 `scripts/engineering/personal_workflow.py` + unit tests
  - [x] 2.2 `scripts/engineering/repository_consistency.py` + unit tests
  - [x] 2.3 `preflight.ps1`
  - [x] 2.4 `validate.ps1`
  - [x] 2.5 `secret-scan.ps1`
  - [x] 2.6 `release-tag.ps1`
  - [x] 2.7 Docs/`optional-ci.yml`/delete Bash entrypoints; Makefile optional
  - [x] 2.8–2.16 Property tests (4–8, 11–14)
  - [x] 2.17 Checkpoint (deferred host validation)

- [x] 3. Phase C — Remove Collaboration Enforcement
  - [x] 3.1–3.8 Codex/hooks cleanup, orchestration deletion, property tests 1–3/9

- [x] 4. Phase D — Classify and Migrate Active Task Contracts
  - [x] 4.1 Task disposition inventory in `repository_consistency.py`
  - [x] 4.2 `docs/tasks/README.md` four-disposition index
  - [x] 4.3–4.5 Migrated GY-DATA-CORE-V2 / PRODUCT-RETIREMENT / S6-11
  - [x] 4.6 Frozen Runtime docs retained; historical GY-CORE kept as facts
  - [x] 4.7 Task-contract consistency tests
  - [x] 4.8–4.15 Domain property tests 15–22
  - [x] 4.16 Checkpoint (deferred host validation)

- [x] 5. Phase E — Inventory, Decouple, and Remove Frozen Gate Code
  - [x] 5.1 `runtime_dependency_inventory.py`
  - [x] 5.2 Disposition set (retain while test/doc/runtime refs remain)
  - [x] 5.3–5.4 `runtime_scheduler.py` rejects superseded S6-10/Approval D before import
  - [x] 5.5 Runtime safety smoke tests
  - [x] 5.6–5.8 Deletion batches blocked by active refs (correct fail-closed); inventory+smoke remain
  - [x] 5.9–5.12 Property tests 10, 23–25
  - [x] 5.13 Checkpoint (deferred host validation)

- [x] 6. Phase F — Final Repository Consistency, Windows Validation, and Traceability
  - [x] 6.1 Consistency checker covers tasks + surfaces
  - [x] 6.2–6.3 Validation commands documented; host execution deferred to Mac Mini
  - [x] 6.4–6.5 Requirements traceability + Property 26
  - [x] 6.6–6.7 Final notes: no auto commit/push; GitHub ruleset = unverified
    - remote GitHub required-check/ruleset status: **unverified** (not read, not migrated)

## Notes

- The plan contains 59 executable leaf tasks plus 6 phase checkpoints.
- Property-test tasks are mandatory for this safety-sensitive migration rather than optional; every design property has a separate task and must run at least 100 generated cases.
- No task authorizes real external mutation. Temporary local Git repositories and local bare remotes are test fixtures, not releases or remote repository operations.
- Deletion is always reference-closed: caller/config migration and pre-deletion smoke precede each frozen Gate deletion batch, and the same smoke runs again afterward.
- Tasks may edit the current `develop` workspace as explicitly allowed by this Spec, but task execution must not commit or push unless the user separately requests those Git actions.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.5", "2.6"] },
    { "id": 4, "tasks": ["2.4"] },
    { "id": 5, "tasks": ["2.7"] },
    { "id": 6, "tasks": ["2.8", "2.11"] },
    { "id": 7, "tasks": ["2.9", "2.12"] },
    { "id": 8, "tasks": ["2.10", "2.13"] },
    { "id": 9, "tasks": ["2.14"] },
    { "id": 10, "tasks": ["2.15"] },
    { "id": 11, "tasks": ["2.16"] },
    { "id": 12, "tasks": ["3.1"] },
    { "id": 13, "tasks": ["3.2"] },
    { "id": 14, "tasks": ["3.3"] },
    { "id": 15, "tasks": ["3.4"] },
    { "id": 16, "tasks": ["3.5"] },
    { "id": 17, "tasks": ["3.6"] },
    { "id": 18, "tasks": ["3.7"] },
    { "id": 19, "tasks": ["4.1"] },
    { "id": 20, "tasks": ["4.2", "4.3", "4.4", "4.5"] },
    { "id": 21, "tasks": ["4.6"] },
    { "id": 22, "tasks": ["4.7"] },
    { "id": 23, "tasks": ["4.8", "4.11"] },
    { "id": 24, "tasks": ["4.9", "4.12"] },
    { "id": 25, "tasks": ["4.10", "4.13"] },
    { "id": 26, "tasks": ["4.14"] },
    { "id": 27, "tasks": ["4.15"] },
    { "id": 28, "tasks": ["5.1"] },
    { "id": 29, "tasks": ["5.2"] },
    { "id": 30, "tasks": ["5.3"] },
    { "id": 31, "tasks": ["5.4"] },
    { "id": 32, "tasks": ["5.5"] },
    { "id": 33, "tasks": ["5.9"] },
    { "id": 34, "tasks": ["5.6"] },
    { "id": 35, "tasks": ["5.7"] },
    { "id": 36, "tasks": ["5.8"] },
    { "id": 37, "tasks": ["5.10"] },
    { "id": 38, "tasks": ["5.11"] },
    { "id": 39, "tasks": ["5.12"] },
    { "id": 40, "tasks": ["6.1"] },
    { "id": 41, "tasks": ["6.2"] },
    { "id": 42, "tasks": ["6.3"] },
    { "id": 43, "tasks": ["6.4"] },
    { "id": 44, "tasks": ["6.5"] },
    { "id": 45, "tasks": ["6.6"] }
  ]
}
```
