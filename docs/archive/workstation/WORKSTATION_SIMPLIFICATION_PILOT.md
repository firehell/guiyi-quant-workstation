# Workstation Simplification Pilot

| Field | Value |
|---|---|
| Date | 2026-07-20 |
| Branch | `codex/workstation-simplify` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/workstation-simplify` |
| Pilot type | Real low-risk API health contract + engineering probe |
| Dispatcher / WorkBuddy | **Not used** |
| Delivery PR | https://github.com/firehell/guiyi-quant-workstation/pull/36 |

## Scope

1. Strengthen liveness health contract in `services/quant-api/app/main.py`（additive `readonly: true`）。
2. Expand `services/quant-api/tests/test_health.py`：alias 一致性、拒绝 POST、禁止凭据字段。
3. Align `scripts/engineering/runtime-health.sh` 只读探针识别 `readonly`。
4. Run via `scripts/engineering/preflight.sh` + pytest（非 CODEX_TASKS / tasks/current 长历史）。

## Local verification

```bash
bash scripts/engineering/preflight.sh --json
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q services/quant-api/tests/test_health.py
python3 -m pytest -q tests/engineering
bash scripts/engineering/runtime-health.sh --json
git diff --check
```

Results (this worktree):

- engineering preflight: exit 0
- `test_health.py`: **6 passed**
- `tests/engineering`: **8 passed**（收口复跑）
- runtime-health: readonly probe exit 0

## Gate status

| Flag | Value |
|---|---|
| Local Pilot evidence | **PASSED** |
| GitHub lifecycle | PR [#36](https://github.com/firehell/guiyi-quant-workstation/pull/36) |
| `REAL_GITHUB_CODEX_PILOT_PASSED` | **PASSED**（随本精简 PR 合入 main；Issue/PR 为任务生命周期，未走 WorkBuddy/dispatcher） |

## Conditions checklist

- [x] 非 Demo；有真实测试
- [x] 使用 engineering preflight / tests
- [x] 未触碰 DB/migration/策略公式/live 写入
- [x] 未走 WorkBuddy/dispatcher
- [x] 精简交付以 PR #36 进入 main（整支合入）
