# 当前项目状态

更新时间：2026-07-10

用途：浏览器 GPT 当前事实速览。代码、数据库和审计产物优先于历史聊天。

## 当前阶段

```text
V1-TRUSTED-CLOSURE
```

当前结论：

- Stage 13-G 已完成，`report_id=14` trust audit 为 `passed`。
- JM 最新主连 `1m/5m/15m/30m/60m/1d` 六周期为 `20230103_20260710_v2 / primary / passed`。
- 5m/15m/30m/60m/1d 均从最新 passed 1m standard parquet 本地聚合，`source_interval=1m`。
- Stage 8.6 全品种 `1d` Gate：82 products passed、8 partial；176 assets passed、8 pending。
- JM 最新主连六周期专用 Gate：6/6 active passed。
- PostgreSQL、Redis 仅绑定 localhost；Redis 已启用环境变量密码。
- JM-only live runtime、交易时钟、1m→5m/15m/30m/60m/1d/1w、盘后归档、正式 live event、notification queue/worker 和监督模板已完成代码与测试；四个真实开关默认关闭。
- 以上只代表 `CODE_COMPLETE_EXTERNAL_GATES_PENDING`：本轮未运行 RQData、未写真实 DB、未发送企业微信、未加载 launchd，也未完成 5 个交易日长稳。
- 公网保留腾讯云 Nginx + FRP 拓扑；验收脚本已覆盖 HTTPS redirect、401/200、WS 101 和业务端口关闭，但真实域名/证书/隧道/重启 smoke 未执行。
- 实施前只读运行态为 API/Web loaded、backtest/signal worker missing、runtime degraded、live checkpoint=0；本轮未改变 launchd 状态。外接卷后台权限仍是实际加载前 Gate。

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
| 1m | 290490 | 2026-07-09 23:00 | RQData direct |
| 5m | 58098 | 2026-07-09 23:00 | aggregated from 1m |
| 15m | 19366 | 2026-07-09 23:00 | aggregated from 1m |
| 30m | 10108 | 2026-07-09 23:00 | aggregated from 1m |
| 60m | 5904 | 2026-07-09 23:00 | aggregated from 1m |
| 1d | 851 | 2026-07-10 00:00 | trading_day aggregation from 1m |

## 回测可信基线

- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- trades：155 mapped
- orders：239 mapped
- audit checks：10/10 passed
- total return：约 -19.29%

该结果只能说明可追溯和内部一致，不能说明策略有效或可实盘。后续只做样本外验证设计，不调参改善收益。

## 功能状态

- Data / Market / Backtest / Signal / Review / Runtime：代码与 API 已形成 V1 研究闭环。
- 企业微信：preview、历史单条受控 smoke、独立 notification queue/worker 和 live-only dispatcher 已实现；autosend 默认关闭，尚无真实 live event send 或长期 worker 证据。
- live：JM-only scheduler、singleton、交易时钟、日/周 confirmed 聚合、恢复骨架和 formal event writer 已实现并测试；尚未做真实 write/restart/soak。
- after-market archive：受控 CLI 和质量链复用已实现；RQData direct real archive 尚未执行。
- 自动交易、实盘账户、委托接口：未实现且禁止扩展。

## 当前风险

- 全品种 pending：`bb/rs/wh/wr/zc` quality warning；`L2609F/PP2609F/V2609F` 缺 DB 登记。
- 真实公网 TLS、Basic Auth、端口封闭和 systemd restart 尚需服务器现场验证。
- macOS 外接卷后台访问需人工授权或迁移运行副本。
- 代码通过不等于长期运行；必须依次完成基础 workers、live write、archive、live event、autosend 和 5 日长稳 Gate。
- 日/周线与夜盘边界已用 fake clock 覆盖，但仍需真实交易日 smoke 验证迟到 revision、主力换月和 RQData 异常。
- 样本外验证未完成。

## 当前任务与事实源

- `tasks/current.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- `data/reports/stage8_6_active_gate_summary.md`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
