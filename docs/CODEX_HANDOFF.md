# CODEX_HANDOFF.md

更新时间：2026-07-16

## 1. 接手结论

当前仓库路径：

```text
/Volumes/扩展盘/guiyi-quant-workstation
```

当前事实源更新任务：`ALL-BRANCH-WORKTREE-MERGE`。

本轮目标是在本地 `main` 上收口所有本地分支和 linked worktree。已创建保护分支：

```text
backup_branch=codex/backup-main-before-all-worktree-merge-20260716
```

已合并到 `main`：

- `task/demo-20260715-004-github-native-v3-final-acceptance`
- `codex/github-task-resolver-parse-task-meta`

已由 DEMO-004 覆盖：

- `codex/ws-gh-013-task-branch-base-validation`

本轮保留 DEMO-004 `.ai/results` 和 `.ai/task-runtime` 证据链，并叠加 resolver 优先读取已存在 worktree task 文件的逻辑。当前不 push、不创建 PR、不删除本地分支引用。

当前验证与清理状态：

- `git branch --no-merged main` 无输出。
- `git worktree list --porcelain` 仅剩主工程 worktree。
- focused workstation 测试通过：`python3 -m pytest -q tests/workstation/test_github_task_resolver.py tests/workstation/test_task_router.py`，`48 passed`。
- 全量 `python3 -m pytest -q tests/workstation` 为 `447 passed, 21 failed`；合并前保护分支对照同样 `447 passed, 21 failed`，属于本轮前已有基线失败。
- `make workstation-test` 失败在 main strict doctor 的 `branch_not_main: current branch=main`。
- runtime/live worktree 已按用户确认删除，如需继续运行本地 runtime 需重新初始化。

---

前一事实源更新任务：`DIRECTION-A-MAIN-MERGE`。

本轮目标是本地受控合并 `feature/direction-a1-final-sealing-audit`。合并策略是保护当前 `main`，选择性接入 Direction A 数据/profile/审计成果；不 push、不删除分支、不写 DB、不写 Parquet、不调用 RQData。

当前本地保护分支：

```text
backup_branch=codex/backup-main-before-direction-a-merge-20260715
integration_branch=codex/merge-direction-a-final-sealing-main
source_branch=feature/direction-a1-final-sealing-audit
```

当前数据层最终状态：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不代表当前数据层最终封板完成。

## 2. 必读顺序

1. `AGENTS.md`
2. `PROJECT_SOURCE.md`
3. `STATUS.md`
4. `CODEX_TASKS.md`
5. `tasks/current.md`
6. `project_sources/00-INDEX.md`
7. `docs/DATA_CENTER.md`
8. `docs/ARCHITECTURE.md`
9. `docs/BACKTEST_ENGINE.md`
10. `docs/SIGNAL_EVENTS.md`

## 3. 当前可信事实

Phase 3 DB 口径：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |

关键边界：

- 105 条 `quality_warning` 保持 warning，不升级为 passed。
- 当前不能宣称“全品种周线从上市以来完整”。
- Stage 9-B2 historical replay single-send smoke 不等于 live-confirmed 或长期发送能力。
- `report_id=14` trust audit passed 不代表策略盈利、稳定或可实盘。
- Direction A 合并只接入 profile registry / active binding / lineage、schema contract、residual root cause audit、multi-primary rulebook 和数据 manifest/report evidence；不得回退当前 Web A01/A02、workstation/GitHub Native V3 或 cross-file conflict warning 语义。

## 4. active 数据硬约束

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、回测和 Stage 9 Gate 默认使用 `quality_status=passed`。禁止 validation、legacy_reference、candidate、旧 TqSdk / 天勤和交易练习者数据进入默认 Market、Backtest、Signal。

## 5. 运行与安全

- PostgreSQL / Redis 只允许本地或受控环境；凭据只走环境变量。
- 企业微信 webhook 只允许从 `QYWX_WEBHOOK_URL` 环境变量读取。
- 不打印或提交 webhook、token、password、license、cookie、证书私钥或账号。
- 不自动下单，不接实盘账户，不新增交易 gateway。
- 不运行 live scheduler 或企业微信批量发送，除非另有明确任务和人工授权。

## 6. 下一步

按优先级另开任务：

1. manifest / DB 对齐专项 Plan。
2. pre-2020 周线 34 品种缺口专项 Plan。
3. JM T3-real 单次 live 写入 Gate。
4. 真实公网安全 smoke。
5. OOS / walk-forward 全窗口验证。

以上涉及数据写入、runtime、scheduler、外部服务或回测口径的任务默认先 Plan。

## 7. 最小验证

文档任务：

```bash
git status --short --branch
git diff --check
git diff --stat
git diff --name-only
```

后端回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests
uv run --project services/quant-api ruff check services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
```

前端回归：

```bash
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
```

回测 trust audit：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id 14 --format markdown
```
