# Lean Matrix V07 GitHub develop Gate 评估器

- 日期：2026-08-03
- 任务：AI-TEAM-007 / Issue #116
- 范围：仓库内纯 evaluator 与只读 CLI；外部 Connector/Codex 集成协议
- 集成状态：task branch 实现与验证证据需经既有独立 Review / CI / merge 流程后才能进入 `develop`

## 1. 目标与非目标

V07 在仓库内只提供一个确定性判定：对 trusted `ExecutionPlanV1` 与已归一化、digest-bound
GitHub/Git facts 评估当前 develop transition 是否可以向前。公开入口是：

```bash
python3 scripts/engineering/lean_matrix_team.py develop-gate \
  --plan <approved-execution-plan.json> \
  --facts <github-gate-facts.json> \
  --format json
```

该命令只读取两个输入文件并向 stdout 输出决策。V07 自身不新增或使用 GitHub client、`gh`、token 管理、
CI/Review poller、ready/merge 客户端、merge daemon、merge executor、receipt writer 或 cleanup executor。仓库既有
`task-worktree.sh` Draft-PR adapter 仍在 V07 之外，其原有边界未变。V07 不实现 `main`、tag、
release、Runtime、live、通知、真实数据/DB、删除、GitHub rules 或任何自动交易操作。

## 2. 权威分工

| 责任 | 所有者 | V07 仓库代码是否执行 |
|---|---|---|
| 解析 trusted plan/Charter 和 normalized facts | V07 evaluator | 是，纯函数 |
| PR、CI、Review、threads、mergeability 读取 | Connector/Codex | 否 |
| local/remote Git SHA 与 ancestry 读取 | Connector/Codex | 否 |
| Draft ready transition | Connector/Codex | 否 |
| expected-head merge-commit 请求 | Connector/Codex | 否 |
| 超时/不确定结果回读 | Connector/Codex | 否 |
| digest-bound merge receipt 写入 | Connector/Codex | 否 |
| clean worktree/branch cleanup | Connector/Codex | 否 |

AI-TEAM-007 不得用新 evaluator 对自身产生集成授权。它必须沿用既有 Connector/Codex flow、
独立 Sol exact-head Review、CI 和用户对本 task→`develop` 的一次性授权。

## 3. 冻结 wire contracts

### 3.1 `GitHubCheckV1`

Exact keys：

```text
schema_version, name, status, head_sha
```

`status` 只能是 `PENDING` / `SUCCESS` / `FAILURE` / `CANCELLED` / `SKIPPED` / `TIMED_OUT` /
`STALE` / `MISSING`；check name 唯一，`head_sha` 必须等于 exact PR head。

### 3.2 `GitHubReviewEvidenceV1`

Exact keys：

```text
schema_version, status, reviewer_context_id, implementer_context_id, head_sha, base_sha,
critical_findings, important_findings, minor_findings, blocking_threads
```

`status` 只能是 `MISSING` / `PENDING` / `APPROVED` / `CHANGES_REQUESTED`。已完成 Review 必须绑定独立
reviewer、exact head 和 frozen base。Critical/Important 是阻断项；Minor 单独不阻断；blocking thread
始终阻断。

### 3.3 `GitHubGateFactsV1`

Exact keys：

```text
schema_version, stage, plan_digest, charter_digest, charter,
repository_id, repository_full_name, pr_number, pr_state, pr_merged, pr_draft,
base_ref, base_sha, head_ref, head_sha, current_task_head_sha, current_develop_sha,
changed_paths, checks, review, pending_external_gates, requested_operations,
change_categories, mergeability, observed_at, expires_at, facts_digest,
readback_merge_sha, readback_develop_contains_task_head, cleanup_worktree_clean,
cleanup_local_develop_contains_task_head, cleanup_remote_develop_contains_task_head
```

`facts_digest` 是除自身以外所有 facts 字段的 semantic SHA-256。`observed_at` 与 `expires_at` 使用
RFC3339 UTC，差值必须恰好五分钟；`now >= expires_at` 即 `FACTS_EXPIRED`，`now < observed_at`
即 `FACTS_FROM_FUTURE`。已构造 dataclass 也必须重序列化并重新校验，不存在快速绕过。

`stage` 只能是 `pre_merge`、`merge_readback`、`cleanup`，其单一 requested operation 分别是
`develop_merge`、`merge_readback`、`cleanup`。`repository_id=1276918660`、
`repository_full_name=firehell/guiyi-quant-workstation`、`base_ref=develop`；head ref 必须是 plan task branch。

Lane 只从完整 `TaskCharterV1` 读取，Charter semantic digest 必须同时匹配 facts 和 plan。Plan 与 Charter
的 issue/task/branch/allowed/forbidden/external Gates 必须相等。`changed_paths` 必须是排序、唯一、仓库相对
路径，并同时通过 frozen scope 与共享 workflow policy。

`change_categories` 必须是无重复闭集：

```text
code, test, dry_run, disabled_feature, isolated_migration
```

Lane 1/2 保持原 `classify_paths()` 行为，并允许空 categories。Lane 3 必须有非空 categories，每个声明类别
都要命中 changed path，每个 path 都要在保守的 source/test/dry-run/migration 正集内。Isolated migration
必须是 `services/quant-api/alembic/versions/` 的直接子文件，并匹配：

```text
^[0-9]{8}_[0-9]{4}_[a-z0-9]+(?:_[a-z0-9]+)*\.py$
```

approval/evidence/receipt/report/production-data 标记、嵌套路径、DB/Parquet 或未知 artifact 均拒绝。

### 3.4 `DevelopGateDecisionV1`

Exact keys：

```text
schema_version, stage, decision, reason_codes, plan_digest, facts_digest, evaluated_at
```

`reason_codes` 必须恰好有一个闭集 reason，并与 stage/decision 组合一致。自由文本不能替代决策。

## 4. 决策与 reason 闭集

| Decision | 允许的 reason |
|---|---|
| `ALLOW_DEVELOP_MERGE` | `DEVELOP_MERGE_ALLOWED`, `READY_TRANSITION_REQUIRED`, `ALREADY_MERGED`, `MERGE_READBACK_CONFIRMED`, `CLEANUP_ALLOWED` |
| `WAIT_CI` | `CI_PENDING` |
| `WAIT_REVIEW` | `REVIEW_PENDING` |
| `BLOCKED_PR_IDENTITY` | `REPOSITORY_ID_MISMATCH`, `REPOSITORY_NAME_MISMATCH`, `PR_BASE_REF_MISMATCH`, `PR_HEAD_REF_MISMATCH`, `PR_CLOSED_UNMERGED` |
| `BLOCKED_HEAD_DRIFT` | `TASK_HEAD_DRIFT`, `CI_HEAD_DRIFT`, `REVIEW_HEAD_DRIFT` |
| `BLOCKED_BASE_DRIFT` | `PR_BASE_SHA_DRIFT`, `REVIEW_BASE_DRIFT`, `CURRENT_DEVELOP_DRIFT` |
| `BLOCKED_SCOPE_DRIFT` | `CHANGED_PATH_FORBIDDEN`, `CHANGED_PATH_OUTSIDE_SCOPE`, `WORKFLOW_CLASSIFICATION_BLOCKED` |
| `BLOCKED_CI` | `CI_CHECK_MISSING`, `CI_FAILURE`, `CI_CANCELLED`, `CI_SKIPPED`, `CI_TIMED_OUT`, `CI_STALE`, `CI_MISSING` |
| `BLOCKED_REVIEW` | `INDEPENDENT_REVIEW_REQUIRED`, `REVIEW_CHANGES_REQUESTED`, `CRITICAL_FINDINGS`, `IMPORTANT_FINDINGS` |
| `BLOCKED_THREADS` | `BLOCKING_THREADS_OPEN` |
| `BLOCKED_MERGEABILITY` | `MERGEABILITY_CONFLICTING`, `MERGEABILITY_UNKNOWN` |
| `MANUAL_GATE_REQUIRED` | `EXTERNAL_GATE_REQUIRED`, `SENSITIVE_OPERATION_REQUESTED`, `WORKFLOW_MANUAL_GATE_REQUIRED` |
| `BLOCKED` | `FACTS_DIGEST_MISMATCH`, `FACTS_MALFORMED`, `FACTS_EXPIRED`, `FACTS_FROM_FUTURE`, `PLAN_DIGEST_MISMATCH`, `CHARTER_DIGEST_MISMATCH`, `PLAN_CHARTER_BINDING_MISMATCH`, `UNKNOWN_EXTERNAL_GATE`, `UNKNOWN_REQUESTED_OPERATION`, `MERGE_RESULT_UNCONFIRMED`, `MERGE_NOT_CONFIRMED`, `WORKTREE_NOT_CLEAN`, `LOCAL_DEVELOP_MISSING_TASK_HEAD`, `REMOTE_DEVELOP_MISSING_TASK_HEAD` |

Stage 绑定也是合同的一部分：CI/Review/threads/mergeability 只在 `pre_merge` 产生对应 reason；
`MERGE_READBACK_CONFIRMED` / `MERGE_RESULT_UNCONFIRMED` 只属于 `merge_readback`；`CLEANUP_ALLOWED` /
cleanup 阻断 reasons 只属于 `cleanup`。Identity、head drift、manual Gate、facts/plan/Charter/scope 校验覆盖
所有阶段。`CURRENT_DEVELOP_DRIFT` 仅在尚未确认合并的 `pre_merge` / `merge_readback` 阶段适用。

## 5. 评估顺序

闭合优先级是：

```text
malformed/tampered/expired facts
-> plan/Charter binding
-> repository and PR identity
-> head drift
-> strict base drift
-> manual Gate / requested operation
-> frozen scope and workflow classification
-> merge_readback or cleanup stage checks
-> required CI
-> independent Review and findings
-> blocking threads
-> mergeability
-> stage-qualified allow
```

任何 current `develop` 在未合并 PR 上偏离 frozen base 都返回 `BLOCKED_BASE_DRIFT`，不做自动 rebase，
不复用旧 Review/CI。需要重新 intake、exact-head Review 和 CI。

## 6. Connector/Codex 集成序列

1. Connector/Codex 完成 fresh `pre_merge` 读取，生成恰好五分钟有效的 facts 和 semantic digest。
2. 运行 evaluator。`WAIT_*` 等待后必须完整重读；任何 blocked/manual 结果停止。
3. Draft 只能通过 `READY_TRANSITION_REQUIRED` 执行 ready transition。Ready 后旧 facts 立即废弃，重读 PR/CI/
   Review/threads/mergeability/current `develop` 并重新评估。
4. 仅 `DEVELOP_MERGE_ALLOWED` 允许 Connector/Codex 发出一次 merge-commit 请求，请求必须绑定该
   facts 中的 expected head SHA。
5. 即使请求返回成功，也必须 readback。如果 timeout/断线/响应不确定，禁止重试 merge；生成 fresh
   `merge_readback` facts。只有 exact head 已 merge、merge SHA 非空、`develop` 包含 task head 时返回
   `MERGE_READBACK_CONFIRMED`。
6. Connector/Codex 在 confirmed readback 后才写 digest-bound merge receipt。Receipt 至少绑定 repository ID/name、
   PR number、frozen base、task head、plan/Charter/facts/decision digests、merge SHA/method、readback time 和
   positive `develop` ancestry。Receipt 是外部编排 evidence，不是新 Gate 或仓库实现声明。
7. 清理必须是独立 `cleanup` transition：生成 fresh facts，再确认 exact-head merge、merge SHA、
   `develop` ancestry、worktree clean，以及 local 和 remote-tracking `develop` 都包含 task head。仅
   `CLEANUP_ALLOWED` 才能让外部编排层删除 clean disposable worktree/branch。

`ALLOW_DEVELOP_MERGE` 不是通用“已完成”标记；它的 reason/stage 决定唯一可前进操作。不得把
`READY_TRANSITION_REQUIRED` 解读为 merge，不得把 `MERGE_READBACK_CONFIRMED` 解读为 cleanup。

## 7. 共享 workflow classifier

公开兼容形式为：

```python
classify_develop_merge(
    lane,
    paths,
    requested_operations,
    external_gates,
    *,
    change_categories=(),
)
```

前四个位置参数冻结不变，`change_categories` 是可选 keyword-only。Lane 1/2 四参调用保持原行为；
Lane 3 四参调用因缺少 category evidence 而 fail-closed。一次只允许 `develop_merge` / `merge_readback` /
`cleanup` 中一个 operation；空、未知或多个 operation 均拒绝。

## 8. 人工 Gate 与验收

以下始终保留原有人工 Gate，任何 V07 决策均不能替代：

- `main` / release / tag；
- Runtime promotion、live enable、真实通知；
- 生产 migration apply、真实数据/canonical/DB 写入；
- 删除 data/evidence/report/receipt/Git 历史；
- 策略/回测正式语义、candidate promotion；
- GitHub 权限与 ruleset；
- 任何下单、撤单、持仓或自动交易路径。

代码验收要求覆盖：全部决策/reason、精确五分钟边界、tamper/重放、strict base/head drift、
Lane 1/2 兼容、Lane 3 category/path 绑定、Draft ready、uncertain readback、already-merged 幂等、cleanup 三重
前置与 CLI 无副作用。真实 Connector 读取、ready/merge/receipt/cleanup 不属于本仓库代码验收，
不得用 fake facts 测试声称已通过外部 Gate。
