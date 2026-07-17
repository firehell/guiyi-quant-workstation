---
kind: Task
schema_version: "2.0"
task_id: B-01-DIRECT-DB-FINAL-BASELINE-AUDIT
title: Direct PostgreSQL 最终基线审计
status: COMPLETED
risk_level: R1
work_level: L2
approval_scope:
  - plan
  - code
allowed_paths:
  - docs/tasks/B-01-DIRECT-DB-FINAL-BASELINE-AUDIT.md
  - scripts/rqdata_direct_db_baseline_audit.py
  - services/quant-api/app/services/rqdata_ingest/direct_db_baseline_audit.py
  - services/quant-api/tests/test_direct_db_baseline_audit.py
  - data/reports/data_layer_direct_db_baseline_*/**
forbidden_paths:
  - .env*
  - data/parquet/**
  - data/manifests/**
  - services/quant-api/alembic/**
  - apps/**
  - packages/**
  - strategies/**
required_tests:
  - PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/test_direct_db_baseline_audit.py services/quant-api/tests/test_target_coverage_audit.py services/quant-api/tests/test_data_layer_final_audit.py
  - uv run --project services/quant-api ruff check scripts/rqdata_direct_db_baseline_audit.py services/quant-api/app/services/rqdata_ingest/direct_db_baseline_audit.py services/quant-api/tests/test_direct_db_baseline_audit.py
  - git diff --check
worktree: /Volumes/扩展盘/guiyi-parallel/b-01-direct-db-baseline
branch: codex/b-01-direct-db-baseline
base_branch: main
owner: Codex
created_at: "2026-07-16"
updated_at: "2026-07-16"
---

# B-01：Direct PostgreSQL 最终基线审计

## 1. 目标

建立阶段 B 的 direct PostgreSQL 数据基线，废除对旧数字和 `manifest_only` 降级结论的依赖。

## 2. 只读边界

- `writes_database=False`
- `writes_parquet=False`
- `writes_manifest=False`
- `writes_quality=False`
- `writes_profile_binding=False`
- `calls_rqdata=False`
- 不调用 API snapshot，不允许 `manifest_only`。

## 3. Gate

必须验证 git commit、branch/worktree、数据根目录、PostgreSQL dialect、direct query、Alembic current/head 和无写入参数。

Direct DB 或 schema Gate 失败时：

```text
BLOCKED_DIRECT_DB_UNAVAILABLE
```

仅生成环境证据和修复建议，不生成覆盖完成度结论。

## 4. 产物

新建且不覆盖：

```text
data/reports/data_layer_direct_db_baseline_<UTC timestamp>/
```

至少包含总结、统一覆盖矩阵、metadata 矩阵、weekly/actual-roll/Profile/cross-file/blocker 列表和环境证据，并明确 B-02/B-03/B-04/B-05 输入文件。

## 5. 验收

- `db_snapshot_source=database`
- 最终分类仅允许 `covered_passed`、`covered_warning`、`not_applicable`、`blocked_with_reason`
- warning 不升级为 passed
- 旧 Phase 3 数字只用于差异解释
- required tests 与 `git diff --check` 通过

## 6. required_tests

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_direct_db_baseline_audit.py \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_data_layer_final_audit.py

uv run --project services/quant-api ruff check \
  scripts/rqdata_direct_db_baseline_audit.py \
  services/quant-api/app/services/rqdata_ingest/direct_db_baseline_audit.py \
  services/quant-api/tests/test_direct_db_baseline_audit.py

git diff --check
```

## 7. 执行记录

实现分支与 worktree：

```text
branch=codex/b-01-direct-db-baseline
worktree=/Volumes/扩展盘/guiyi-parallel/b-01-direct-db-baseline
base_commit=d54e0198a426cce8fc2df3be361a29cc53145c9e
```

历史 blocked 运行（保留为环境快照）：

```text
BLOCKED_DIRECT_DB_UNAVAILABLE
reason=fe_sendauth: no password supplied
output=data/reports/data_layer_direct_db_baseline_20260716T140929Z/
```

该目录仅包含环境证据、阻塞清单和修复建议；未生成覆盖完成度矩阵，也未使用 API/`manifest_only` fallback。

最终 direct PostgreSQL 运行（2026-07-17）：

```text
DIRECT_DB_BASELINE_READY
db_snapshot_source=database
audit_end=2026-07-10
writes_database=false
writes_parquet=false
writes_manifest=false
writes_quality=false
writes_profile_binding=false
calls_rqdata=false
```

最终报告输出于：

```text
data/reports/data_layer_direct_db_baseline_20260717T000000Z/
```

自动化验证：39 passed，ruff clean，`git diff --check` passed。当前指标是 B-01 的 direct-DB 事实快照；`blocked_with_reason=22324`、`actual_roll_gaps=18592` 等是 B-02..B-05 的输入，不代表本只读基线 Gate 失败。
