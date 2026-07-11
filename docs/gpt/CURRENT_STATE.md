# 当前项目状态

更新时间：2026-07-11

用途：浏览器 GPT 当前事实速览。代码、数据库和审计产物优先于历史聊天。

## 当前阶段

```text
V1-TRUSTED-CLOSURE
→ TASK-2026-07-11-001-data-asset-audit DELIVERY_READY_WITH_CLI_ENV_NOTE
```

当前结论：

- Stage 13-G 已完成，`report_id=14` trust audit 为 `passed`。
- JM 最新主连 `1m/5m/15m/30m/60m/1d` 六周期为 `20230103_20260711_v2 / primary / passed`。
- 5m/15m/30m/60m/1d 均从最新 passed 1m standard parquet 本地聚合，`source_interval=1m`。
- Stage 8.6 全品种 `1d` Gate 当前 data-audit snapshot：82 products passed、8 partial；1326 manifest-level discovered active records passed、8 pending。
- JM 最新主连六周期专用 Gate：6/6 active passed。
- 数据盘点 direct CLI 已尝试，但本 `data-audit` worktree 无 `.env` / `DATABASE_URL`，默认无密码 DB 连接失败；为避免读取凭据，盘点报告使用本机已运行 API readonly snapshot 读取 DB metadata。
- 当前分支只能验收为 `Stage 8.6 Active Gate 只读快照完成`，不能验收为 `全量历史数据资产盘点完成`。
- PostgreSQL、Redis 仅绑定 localhost；Redis 已启用环境变量密码。
- 公网保留腾讯云 Nginx + FRP 拓扑，已收敛为 HTTPS + Basic Auth；Mac mini 侧由 launchd 监督 static/API/workers，但尚未完成真实 TLS/防火墙/隧道/重启 smoke。
- macOS launchd 因仓库位于外接卷而被系统拒绝读取 `.env`；失败 LaunchAgents 已卸载，未留下重启循环。

## 主链路

```text
RQData 1m -> standard 1m quality passed
-> local aggregation -> manifest/checksum/DB metadata
-> DuckDB -> vn.py/FastAPI -> Web/Report/Review/Signal
```

active 入口：

```text
provider in (rqdata, local_parquet)
data_role = primary
quality_status != failed
```

严格研究使用 `quality_status=passed`。

## JM 数据

| period | rows | max datetime | derivation |
|---|---:|---|---|
| 1m | 290715 | 2026-07-10 15:00 | RQData direct |
| 5m | 58143 | 2026-07-10 15:00 | aggregated from 1m |
| 15m | 19381 | 2026-07-10 15:00 | aggregated from 1m |
| 30m | 10116 | 2026-07-10 15:00 | aggregated from 1m |
| 60m | 5909 | 2026-07-10 15:00 | aggregated from 1m |
| 1d | 851 | 2026-07-10 00:00 | trading_day aggregation from 1m |

## 数据资产盘点

- 任务：`TASK-2026-07-11-001-data-asset-audit`
- 报告目录：`data/reports/data_audit_20260711/`
- direct CLI 状态：已尝试，因本 worktree 无 DB 认证环境失败；未读取 `.env` 或凭据。
- fallback 数据源：本机已运行 API readonly data-center snapshot。
- 产品层结论：82 `active_passed` / 8 `active_partial`。
- 当前 snapshot 资产口径：1326 `active_passed` / 8 `audit_pending`，仅表示 manifest-level discovered active records；唯一键限定为 `product + asset_scope + contract + period + standard_path`。
- `1326` 构成：`actual_contract` 1241 passed / 3 pending，`dominant_main` 85 passed / 5 pending；当前 profile 全部为 `1d`，不是多周期全量覆盖。
- DuckDB row count 和 datetime boundary 已核对；checksum 未在本报告中逐文件独立证明。
- 8 pending 不阻塞 JM V1-B；JM 最新主连六周期仍为 6/6 `active_passed`。
- Stage 9 仍为 90 `stage9_blocked`，本任务不授权企业微信发送。
- 下一步不直接修 8 pending，先另开 Plan-mode 任务 `codex/data-target-coverage-audit`，产出目标资产目录与完整覆盖矩阵。

## 回测可信基线

- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- trades：155 mapped
- orders：239 mapped
- audit checks：10/10 passed
- total return：约 -19.29%

该结果只能说明可追溯和内部一致，不能说明策略有效或可实盘。后续只做样本外验证设计，不调参改善收益。

## 功能状态

- Data / Market / Backtest / Signal / Review / Runtime：代码与 API 已形成 V1 研究闭环。
- Web 视觉：已完成克制科技感设计系统、四组导航、真实 Dashboard 指标、Signal 宽表和 K 线 1440/1280/1024 响应式；11 路由 browser smoke 无 console error/warning。
- 企业微信：preview、单条受控发送和通知记录已完成；没有自动 scheduler。
- live：ingest/aggregation/evaluator 代码存在；没有长期 scheduler，live tables/checkpoints 不代表正在运行。
- 自动交易、实盘账户、委托接口：未实现且禁止扩展。

## 当前风险

- 全品种 Stage 8.6 pending：`bb/rs/wh/wr/zc` quality warning；`L2609F/PP2609F/V2609F` 缺 DB 登记。它们只是当前 `stage8_6_1d_first` profile 的问题，不代表完整目标覆盖缺口全集。
- 真实公网 TLS、Basic Auth、端口封闭和 systemd restart 尚需服务器现场验证。
- macOS 外接卷后台访问需人工授权或迁移运行副本。
- 样本外验证未完成。

## 当前任务与事实源

- `tasks/current.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `data/reports/stage8_6_active_gate_summary.md`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
- `data/reports/data_audit_20260711/DATA_ASSET_INVENTORY.md`
- `data/reports/data_audit_20260711/stage8_6_active_gate_summary.md`
- `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
