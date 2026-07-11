# CODEX_HANDOFF.md

更新时间：2026-07-10

## 1. 接手结论

当前实施分支：`codex/v1-live-runtime-closure`，隔离 worktree 为 `/Volumes/扩展盘/guiyi-quant-workstation-live-runtime`，基于 `a7df3aac`。原 `codex/web-visual-refactor-v1b` 脏工作区未被修改。

接手时先运行：

```bash
git rev-parse --show-toplevel
git status --short --branch
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
- assets：176 active passed / 8 audit pending
- pending：5 个主连 quality warning，3 个 actual-contract 缺 DB 登记
- Stage 9 readiness：90 blocked；本报告不授权企业微信发送

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
- JM-only scheduler、交易时钟、日/周 confirmed 聚合、盘后归档、formal live event、notification queue/worker 和日志轮转模板已完成代码测试；四个真实 feature flags 默认关闭。
- 实施前运行态为 API/Web loaded、backtest/signal worker missing、runtime degraded、live checkpoint=0；本轮未加载/卸载 launchd。外接卷权限仍未解除，不能宣称开机自启通过。

## 5. 禁止事项

- 不自动下单，不接实盘账户，不新增交易 gateway。
- 未经逐 Gate 确认，不运行 live write/archive、不开 autosend、不加载 scheduler/notification LaunchAgent。
- 不打印或提交 webhook/token/password/license/cookie/证书私钥。
- 不把 `jm.MAIN` 当成可交易合约或 trigger price。
- 不把 Stage 13 passed 当成模拟盘/实盘准入。
- 不修改旧策略版本以改善收益。

## 6. 下一步

按优先级另开任务：

1. 先恢复 API/Web/backtest/signal 基础监督，不开启 live flags。
2. 依次做 JM 单次 live/restart、archive、formal event、单条 live notification smoke。
3. 完成 5 个交易日长稳和腾讯云真实域名验收。
4. 8 个全品种 pending 的只读审计和受控修复，再逐品种扩 realtime allow-list。
5. 样本外 / walk-forward 验证设计。

## 7. 必读文件

- `AGENTS.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
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
