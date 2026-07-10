# 当前任务：V1-TRUSTED-CLOSURE

生成时间：2026-07-10
任务性质：V1 可信闭环基线收口、公网安全 Gate、长期运行收口、JM 多周期数据一致性与只读验收

## 当前状态

`DELIVERY_READY_WITH_EXTERNAL_GATES`

实施前 checkpoint：`921792ab chore: checkpoint before V1 trusted closure`

历史 Stage 8.5 至 Stage 13-F 流水已归档到：

- `tasks/done/2026-07-07-to-2026-07-09-stage8_5-to-stage13f.md`

## 目标

1. 将 Stage 13-G 当前真实结果冻结为 `report_id=14 / audit_status=passed`。
2. 统一 README、架构、数据中心、回测、交接和 GPT 状态文件。
3. 收紧公网部署边界：DB / Redis 仅本机监听，凭据只来自环境变量，Nginx 强制 HTTPS 与访问控制。
4. 将长期运行从 Vite dev / uvicorn reload / oneshot 改为可监督的 API、Web、backtest worker、signal worker 服务。
5. 审查并应用 Alembic `20260710_0020`。
6. 以最新 JM `1m` standard parquet 为唯一源，本地生成并登记 `5m/15m/30m/60m/1d`。
7. 重跑 Stage 8.6、Stage 13 trust audit、全量测试和浏览器只读 smoke。

## 硬边界

- 不修改策略入场、出场、止损、止盈或参数，不优化收益。
- 不接实盘账户，不新增交易或委托接口，不自动下单。
- 不运行 live ingest / scheduler，不自动发送企业微信。
- active 数据入口保持：`provider in (rqdata, local_parquet)`、`data_role=primary`、`quality_status!=failed`；严格研究使用 `quality_status=passed`。
- 最新多周期资产必须遵循：`1m standard parquet -> 本地聚合 -> quality passed -> active 登记`。
- 不提交 `.env`、密码、token、webhook、license 或证书私钥。

## 实施步骤

- [x] Step 0：检查工作区、敏感信息并建立 Git checkpoint。
- [x] Step 1：文档事实源收口。
- [x] Step 2：公网与凭据安全配置收口；远端 TLS / 认证 / 端口实测保留 Gate。
- [x] Step 3：systemd 监督配置与 Alembic head 收口；macOS 外置盘 LaunchAgent 重启验收保留 Gate。
- [x] Step 4：JM 最新 `1m` 派生多周期与质量登记。
- [x] Step 5：全量测试、trust audit、运行态和六页面浏览器验收。
- [x] Step 6：交付记录、风险与 GPT 同步清单。

## 当前已确认事实

- Stage 13-G：`report_id=14` 有 155 笔 trade、239 条 order，全部为 mapped；本轮 trust audit 九类检查均 `passed`。
- 该报告 `total_return=-0.1928553100985149`，可信通过不等于策略盈利或可实盘。
- JM 最新 `1m`：`rqdata_jm_standard_1m_20230103_20260710_v2`，290490 行，最大自然时间 `2026-07-09 23:00:00`，质量 `passed`。
- 派生资产已重建：`5m=58098`、`15m=19366`、`30m=10108`、`60m=5904`、`1d=851`；均为 `local_parquet / primary / passed`，来源为最新 passed `1m`。
- Stage 8.6 `stage8_6_1d_first`：90 products，82 `active_passed`、8 `active_partial`；176 assets passed、8 audit pending；Stage 9 readiness 仍为 90 blocked。
- JM `jm_main_six_period_latest`：1 product、6 assets 全部 `active_passed`，审计只读且不授权通知发送。
- PostgreSQL / Redis 仅绑定 `127.0.0.1`；Redis 未认证返回 `NOAUTH`，认证健康检查返回 `PONG`。
- Alembic current/head 均为 `20260710_0020 (head)`。
- 六页面浏览器 smoke 均为 0 console errors；Runtime 显示 `overall=ok`、2 workers，并明确所有 `would_*` 为 false。
- `dev-down.sh` 进程树清理复测通过；API/Web/两个 worker 子进程全部退出，8000/5173 关闭且无 stale PID 文件。

## 验收命令

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests
uv run --project services/quant-api ruff check services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
cd services/quant-api && uv run python -m alembic current && uv run python -m alembic heads
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id 14 --format markdown
bash scripts/dev-status.sh --json
bash scripts/dev-healthcheck.sh --json --no-start
git diff --check
```

## Gate

任何迁移失败、JM 聚合质量非 `passed`、active 登记不一致、trust audit 退化、敏感信息命中或浏览器出现关键错误，均停止后续步骤并保留当前产物，不伪装完成。

## 尚未解除的外部 Gate

1. 未在实际公网主机验证 TLS 证书、Basic Auth 和 5432/6379 外网不可达；本轮只完成配置、语法和本机端口验证。
2. macOS LaunchAgent 无权读取外置盘 `/Volumes/扩展盘` 下项目 `.env`；失败 job 已卸载，必须先由用户授予访问权限或迁移运行目录，再做重启恢复验收。
3. `research_only` 字段未重命名；数据角色与非交易用途提示的 schema/API 兼容拆分留给独立 Plan。

完整交付证据见：`docs/tasks/V1-TRUSTED-CLOSURE-ACCEPTANCE.md`。
