# CODEX_HANDOFF.md

更新时间：2026-07-12

## 1. 接手结论

当前分支：`main`。最新交付任务：`POST-DATA-CLOSURE-GATE-EXECUTION`（方案 B 迁移 + readiness + OOS CLI）。

数据内容审计 worktree（`/Volumes/扩展盘/guiyi-parallel/data-audit`）已于 2026-07-12 收口合并至 main（`8ab908dd`）；工作站 V1.5 控制平面已于同日合并（`3898ec96`）。后续数据审计只在主工程继续。

接手时先运行：

```bash
git rev-parse --show-toplevel
git status --short --branch
make workstation-test   # 工作站控制平面自检（feature/unified-task-dispatcher）
sed -n '1,240p' tasks/current.md
```

不要覆盖用户未提交文件；`.env`、`.run`、用户 LaunchAgents 和真实凭据不入库。

## 2. 当前可信事实

### Stage 13-G

- `report_id=14`
- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- 155 trades 全部 mapped
- 239 orders 全部 mapped
- trust audit 10/10 passed
- total return 约 -19.29%

审计通过只代表可追溯和内部一致，不代表策略有效。下一步只允许样本外验证设计，不调参改善收益。

### JM 最新主连数据

- version window：`20230103_20260710_v2`
- 1m：290490 rows / passed / RQData direct
- 5m：58098 rows / passed / aggregated from 1m
- 15m：19366 rows / passed / aggregated from 1m
- 30m：10108 rows / passed / aggregated from 1m
- 60m：5904 rows / passed / aggregated from 1m
- 1d：851 rows / passed / grouped by trading_day from 1m
- `jm_main_six_period_latest`：6/6 active passed

### 全品种 Stage 8.6

- products：82 active passed / 8 active partial
- manifest-level discovered active records：1326 active passed / 8 audit pending
- pending：5 个主连 quality warning，3 个 actual-contract 缺 DB 登记
- Stage 9 readiness：90 blocked；本报告不授权企业微信发送

### Stage 5-B reference metadata gap

- `TASK-2026-07-12-009-reference-metadata-gap-apply` 已收口为 `DELIVERY_READY_STAGE_5B_REFERENCE_METADATA_GAP_CLOSED_QUALITY_WARNING_GATE`。
- `contract_universe`：285 candidates / 285 success / `rows_fetched_sum=652928`。
- derived `continuous_contract_map`：546 candidates / 546 success / `rows_fetched_sum=234812` / `calls_rqdata=False`。
- final target coverage：`covered_passed=17203`、`covered_warning=105`、`not_applicable=273`、`issue_register_rows=105`。
- 剩余 105 条 `quality_warning` 是独立后续 Gate，不得升级为 `passed`，不授权 Stage 9、企业微信发送或自动交易。
- derived continuous map 不能写成 RQData SDK `get_continuous_contracts` 直接接口验收。

### DATA-PART-TARGET-CLOSURE

- 数据部分已完成：`DATA-PART-TARGET-CLOSURE DELIVERY_READY`。
- 五条件均满足：reference metadata gap closed、105 条 `quality_warning` 消费边界、Stage 8.6 pending 分流、消费者统一 active/strict passed 入口、最终文档/报告/测试事实源。
- final target coverage：`covered_passed=17203`、`covered_warning=105`、`metadata_gap=0`、`not_applicable=273`、`issue_register_rows=105`。
- 105 条 `quality_warning` 保留 warning，不得升级为 passed。

### POST-DATA-CLOSURE-GATE-EXECUTION（Cursor 2026-07-12）

- 方案 B 迁移完成：launchd 绑定 `~/GuiyiRuntime/guiyi-quant-workstation-runtime`（`ops/local-runtime-disk`）；旧 parallel 已 bootout；`dev-healthcheck` passed。
- TASK-017 Phase 1 dry-run passed；T3 runtime 副本非交易 smoke → `idle`；live 四表 count=0。
- 可标记 `SCHEME_B_MIGRATION_PASSED` / `POST_DATA_CLOSURE_PHASE1_DRY_RUN_PASSED`；不可标记 `T3_REAL_PASSED` / `JM_RUNTIME_READY` / `LONG_RUNNING_READY`。
- OOS：`configs/oos/jm_v1b_report14_frozen.json` + `scripts/oos_validation_run.py`；report 14 trust audit 复现 passed。
- 证据：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §11–§12、`docs/tasks/TASK-2026-07-12-019-macos-scheme-b-migration-impl.md`

### POST-DATA-CLOSURE-GATE-EXECUTION

- Cursor 已完成：TASK-017 Phase 1 dry-run；方案 B 迁移至 `~/GuiyiRuntime/guiyi-quant-workstation-runtime`；T3 runtime 副本非交易 smoke（idle）；report 14 trust audit 复现；OOS frozen CLI。
- launchd supervised runtime root 现为 `~/GuiyiRuntime/guiyi-quant-workstation-runtime`（`ops/local-runtime-disk`）。
- 可标记：`SCHEME_B_MIGRATION_PASSED`、`POST_DATA_CLOSURE_PHASE1_DRY_RUN_PASSED`、`T3_RUNTIME_COPY_SMOKE_IDLE_NON_TRADING`。
- 不可标记：`T3_REAL_PASSED`、`JM_RUNTIME_READY`、`LONG_RUNNING_READY`。

## 3. active 数据硬约束

```text
provider in (rqdata, local_parquet)
data_role = primary
quality_status != failed
```

严格研究使用 passed。禁止 validation、legacy_reference、candidate、旧 TqSdk / 天勤和交易练习者数据进入默认 Market、Backtest、Signal。

最新派生周期必须遵守：

```text
passed 1m standard -> local aggregation -> quality passed -> active registration
```

## 4. 运行与安全

- Compose PostgreSQL / Redis 只绑定 `127.0.0.1`。
- Redis 使用 `REDIS_PASSWORD`；生产 DB/Redis URL 只允许环境变量。
- `dev-up.sh` 不回显完整连接串，清理 stale PID 后启动开发服务。
- 公网：腾讯云 Nginx HTTPS + Basic Auth，经 FRP 转发到 Mac mini 受监督的 static `dist` / API；两个 worker 只在本地运行。
- 真实域名、TLS、防火墙、未认证 401、FRP 端口限制和 restart recovery 尚未远程验收。
- macOS launchd 因仓库位于外接卷而被系统拒绝读取 `.env`；失败 jobs 已卸载。不能宣称开机自启通过。

## 5. 禁止事项

- 不自动下单，不接实盘账户，不新增交易 gateway。
- 不运行 live scheduler 或企业微信批量发送。
- 不打印或提交 webhook/token/password/license/cookie/证书私钥。
- 不把 `jm.MAIN` 当成可交易合约或 trigger price。
- 不把 Stage 13 passed 当成模拟盘/实盘准入。
- 不修改旧策略版本以改善收益。

## 6. 下一步

按优先级另开任务：

1. **T3-real 单次 live 写入**：JM 可交易时段 + 用户显式确认；于 `~/GuiyiRuntime/guiyi-quant-workstation-runtime` 执行 TASK-017 Phase 2/3。
2. OOS 全窗口批量：`scripts/oos_validation_run.py --run`（默认不入库）。
3. 5 交易日长稳 + kill/recovery → 评估 `LONG_RUNNING_READY`。
4. 真实服务器安全与恢复 smoke。
5. Web trust audit 展示和公共 chunk 拆包。

live scheduler、after-market archive、formal signal event、企业微信 autosend 和 `research_only` schema 拆分继续后置。

## 7. 必读文件

- `AGENTS.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/tasks/TASK-2026-07-12-015-supervisor-service-gate.md`
- `docs/tasks/TASK-2026-07-12-017-jm-single-live-gate-plan.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `deploy/nginx/README.md`

## 8. 最小验证

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests
uv run --project services/quant-api ruff check services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
cd services/quant-api && uv run python -m alembic current && uv run python -m alembic heads
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id 14 --format markdown
git diff --check
```
