# Workstation Simplification Final Report

| Field | Value |
|---|---|
| Date | 2026-07-20 |
| Branch | `codex/workstation-simplify` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/workstation-simplify` |
| Final mode | `WORKSTATION_SIMPLIFIED` + `WORKSTATION_MAINTENANCE_ONLY` |
| Delivery PR | https://github.com/firehell/guiyi-quant-workstation/pull/36 |

## Outcome

工作站控制面已从 GitHub Native V3 + WorkBuddy/CodeBuddy/dispatcher 多入口，收敛为：

```text
GitHub Issue/PR + GPT + Codex + 用户
STATUS.md 唯一项目状态
docs/DEVELOPMENT.md 唯一开发流程
scripts/engineering/* 正式工程入口
```

业务 deep canonical（ARCHITECTURE / DATA_CENTER / BACKTEST / SIGNAL）与业务 Gate **未改写**。

## Step results

| Step | Status | Commit message prefix |
|---|---|---|
| 0 Inventory | done | `WS-SIMPLIFY-00` |
| 1 Canonical docs | done | `WS-SIMPLIFY-01` |
| 2 State sources | done | `WS-SIMPLIFY-02` |
| 3 Docs archive | done | `WS-SIMPLIFY-03` |
| 4 Engineering entrypoints | done | `WS-SIMPLIFY-04` |
| 5 Real Pilot | done | `WS-SIMPLIFY-05` + PR #36 |
| 6 Legacy removal | done | `WS-SIMPLIFY-06` |
| 7 Final freeze | done | `WS-SIMPLIFY-07` |

## Tests (local)

```bash
bash -n scripts/engineering/*.sh
python3 -m pytest -q tests/engineering   # 8 passed
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_health.py  # 6 passed
git diff --check
```

## Retained safety capabilities

见 [`STEP6_RETENTION.md`](STEP6_RETENTION.md)。

## Pilot Gate

```text
REAL_GITHUB_CODEX_PILOT_PASSED
```

证据：本地 health/engineering 测试 + 交付 PR [#36](https://github.com/firehell/guiyi-quant-workstation/pull/36)。详见 [`WORKSTATION_SIMPLIFICATION_PILOT.md`](WORKSTATION_SIMPLIFICATION_PILOT.md)。

## Known residuals

- `configs/ai/**` Codex profile 模板保留，待另审。
- `scripts/env/check_task_env.sh` 为 deprecated shim。
- `CODEX_TASKS.md` / `tasks/current.md` 为兼容指针。
- 历史 `docs/tasks/**` 与 ADR-WS-001 仍可能提及旧 dispatcher（归档语义）。
- `check-secrets.sh` 对代码中 `DATABASE_URL=` 赋值形态仍有少量 family 命中（不打印值；非 `--strict` 不失败）。
- GPT 浏览器对 PR #36 的外部 Review：请在 merge 前或后补做（本收口已开 PR）。

## Follow-ups（人工）

1. 按 [`GITHUB_LEGACY_ISSUE_PR_CLEANUP.md`](GITHUB_LEGACY_ISSUE_PR_CLEANUP.md) 人工关闭旧 Issue/PR。
2. 确认 CI `workstation-test` 走 engineering 入口。
3. （建议）GPT 浏览器 Review PR #36 diff。
