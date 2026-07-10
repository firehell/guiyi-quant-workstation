# V1 Trusted Closure Acceptance

日期：2026-07-10
状态：`DELIVERY_READY_WITH_EXTERNAL_GATES`
实施前 checkpoint：`921792ab chore: checkpoint before V1 trusted closure`

## 1. 交付结论

V1 可信研究闭环的本地代码、数据、迁移、可信回测回归和六页面只读 smoke 已通过。公网远端安全和 macOS 外置盘重启恢复仍是外部环境 Gate，不能宣称完成生产验收。

本轮没有修改策略收益逻辑，没有新增交易或账户接口，没有运行 live ingest / scheduler，没有发送企业微信，也没有自动 push、merge 或 deploy。

## 2. 文档与任务基线

- 当前任务已收缩为 `V1-TRUSTED-CLOSURE`。
- Stage 8.5 至 Stage 13-F 流水已归档到 `tasks/done/2026-07-07-to-2026-07-09-stage8_5-to-stage13f.md`。
- README、ARCHITECTURE、DATA_CENTER、BACKTEST_ENGINE、CODEX_HANDOFF 与 GPT 状态文件已统一到 2026-07-10 事实。
- Stage 13-G 基线固定为 `report_id=14 / audit_status=passed`，同时保留“可信不等于盈利或可实盘”的结论。

## 3. 公网与凭据安全

- PostgreSQL 和 Redis 的 Docker host 端口均只绑定 `127.0.0.1`。
- Redis 启用密码认证；未认证 `PING` 返回 `NOAUTH Authentication required`。
- 应用与 Alembic 不再使用仓库内硬编码数据库密码 fallback。
- 启动日志不打印完整 `DATABASE_URL` / `REDIS_URL`。
- Nginx 模板强制 HTTP 跳转 HTTPS、启用 TLS 1.2/1.3、Basic Auth、HSTS 和安全响应头。
- `public-healthcheck.sh` 要求显式 HTTPS URL，验证未认证 401 与认证后 200。

未完成：真实公网域名、证书、Basic Auth 和 5432/6379 外网不可达尚未在远端主机执行验收。

## 4. 长期运行与迁移

- 当前公网拓扑保留腾讯云 Nginx + FRP；Mac mini launchd 模板拆分为 API、静态 Web、backtest worker、signal worker，不使用 Vite dev、`uvicorn --reload` 或 oneshot 启动整套服务。
- systemd 的 API/worker restart policy 模板保留为未来 Linux 同机运行候选，不作为本轮已部署事实。
- 本地脚本增加 stale PID 清理和结构化状态输出。
- Alembic `current` 与 `heads` 均为 `20260710_0020 (head)`。

未完成：macOS LaunchAgent 被系统隐私策略拒绝读取外置盘项目 `.env`。失败 job 已全部卸载，安装脚本默认拒绝在 `/Volumes/*` 直接 load，除非用户显式授权并设置确认变量。

## 5. JM 多周期可信数据

唯一聚合源：

- `rqdata_jm_standard_1m_20230103_20260710_v2`
- rows: `290490`
- max datetime: `2026-07-09 23:00:00`
- `quality_status=passed`

本地派生并登记：

| period | rows | provider | role | quality | lineage |
|---|---:|---|---|---|---|
| 1m | 290490 | rqdata | primary | passed | direct standard source |
| 5m | 58098 | local_parquet | primary | passed | aggregated_from_1m |
| 15m | 19366 | local_parquet | primary | passed | aggregated_from_1m |
| 30m | 10108 | local_parquet | primary | passed | aggregated_from_1m |
| 60m | 5904 | local_parquet | primary | passed | aggregated_from_1m |
| 1d | 851 | local_parquet | primary | passed | grouped by trading_day from 1m |

`jm_main_six_period_latest` 只读 Gate：1 product、6 assets 全部 `active_passed`。

全品种 `stage8_6_1d_first` Gate：90 products、82 `active_passed`、8 `active_partial`；176 assets passed、8 audit pending。8 个 pending 是既有全品种数据问题，不由 JM 六周期收口掩盖。

## 6. 回测可信回归

`report_id=14` 结果：

- `audit_status=passed`
- 155 trades、239 orders，lineage mapping 完整
- data lineage、execution policy、trade/order consistency、equity consistency、fee/slippage、multiplier、trusted metrics、reproducibility、sensitive output 全部 passed
- `total_return=-0.1928553100985149`

结论：该报告可作为可信回归基线，但收益为负；下一轮只能先设计样本外验证，不得以调参改善收益作为本轮收口内容。

## 7. 测试与 smoke 证据

- 后端：`331 passed in 8.22s`
- ruff：全量通过
- 前端：6 files / 27 tests passed
- 前端 build：通过；保留一个 650.88 kB chunk size warning
- Alembic：`20260710_0020 (head)`
- Trust audit：`report_id=14 / passed`
- Docker：PostgreSQL `127.0.0.1:5432`；Redis `127.0.0.1:6379`
- Redis：未认证 `NOAUTH`；认证 `PONG`
- 浏览器：Data、Market、Backtest、Signal、Review、Runtime 均加载成功且 0 console errors
- Market：`JM2609 / 15m / 1471 bars / quality passed`，页面明确只读且不自动下单
- Runtime：`overall=ok`、PostgreSQL/Redis/RQ 均 ok、2 workers，`would_start_services=false`、`would_enqueue_jobs=false`、`would_send_notifications=false`

## 8. 后续独立 Plan

1. 公网远端 TLS / Basic Auth / 端口不可达、FRP 限制与受监督服务重启恢复验收。
2. macOS 外置盘权限解决后的 LaunchAgent reboot smoke。
3. `research_only` 的 schema/API 兼容拆分设计。
4. `report_id=14` 样本外验证设计，不调参改善收益。
5. live ingest / scheduler 只读观察与提醒 Plan，不自动下单。
