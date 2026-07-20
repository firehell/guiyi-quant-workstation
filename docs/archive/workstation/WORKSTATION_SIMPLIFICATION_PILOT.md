# Workstation Simplification Pilot

| Field | Value |
|---|---|
| Date | 2026-07-20 |
| Branch | `codex/workstation-simplify` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/workstation-simplify` |
| Pilot type | Real low-risk API health contract + engineering probe |
| Dispatcher / WorkBuddy | **Not used** |

## Scope

1. Strengthen liveness health contract in `services/quant-api/app/main.py`（additive `readonly: true`）.
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
- `tests/engineering`: **7 passed**
- runtime-health: readonly probe exit 0

## Step 6 gate status

| Flag | Value |
|---|---|
| Local Pilot evidence | **PASSED** |
| `REAL_GITHUB_CODEX_PILOT_PASSED` | `LOCAL_READY_PENDING_USER_MERGE` |

说明：本环境未执行 GitHub PR merge。按用户指示，Step 5 本地证据充分后**继续 Step 6**，但删除必须以 `git grep` / CI / Makefile 证据为准；仍被强依赖的入口只 deprecated 不删。

## Conditions to enter Step 6（本分支判断）

- [x] 非 Demo；有真实测试
- [x] 使用 engineering preflight / tests
- [x] 未触碰 DB/migration/策略公式/live 写入
- [x] 未走 WorkBuddy/dispatcher
- [ ] 用户 merge 到 main（pending；不阻塞本分支 Step 6 的 grep 驱动删除）
