# 归一量化项目快照

更新时间：2026-07-10

## 项目定位

本地、单用户的国内期货研究工作站：数据更新、质量、K线、策略、回测、报告、复盘、信号提醒和人工观察。V1 不自动交易，不接实盘账户，不做 SaaS。

## 技术架构

- Web：Vue 3、Vite、TypeScript、Naive UI、Lightweight Charts、ECharts。
- API：FastAPI、Pydantic、SQLAlchemy、Alembic。
- 队列：Redis、RQ。
- 数据：RQData、Parquet、DuckDB、PostgreSQL metadata/facts。
- 回测：vn.py CTA + 自定义 Adapter/Runner/ResultConverter/Trust Audit。
- 本地依赖：Docker Compose；公网模板：腾讯云 Nginx HTTPS + FRP，Mac mini launchd 监督服务。

## active 数据链路

```text
RQData 1m -> standard 1m quality passed
-> local 5m/15m/30m/60m/1d aggregation
-> manifest/checksum/DB metadata
-> DuckDB -> Market/Backtest/Signal/Review
```

```text
provider in (rqdata, local_parquet)
data_role = primary
quality_status != failed
```

## JM 最新资产

| period | rows | max datetime | quality |
|---|---:|---|---|
| 1m | 290490 | 2026-07-09 23:00 | passed |
| 5m | 58098 | 2026-07-09 23:00 | passed |
| 15m | 19366 | 2026-07-09 23:00 | passed |
| 30m | 10108 | 2026-07-09 23:00 | passed |
| 60m | 5904 | 2026-07-09 23:00 | passed |
| 1d | 851 | 2026-07-10 00:00 | passed |

1m 来自 RQData direct，其余五周期为 `aggregated_from_1m`。专用 Gate：6/6 active passed。

## 当前功能

- 数据中心、主力映射、交易参数、质量报告和研究面板。
- historical/live 显式 K 线视图；live 默认不进入 active。
- vn.py 回测、批量任务、报告、equity/drawdown、trade/order、K线 marker。
- Stage 13 trust audit 与复盘 note。
- 信号扫描、signal_events、Stage 9 Gate、企业微信受控单条提醒。
- runtime health API 和 Web 只读状态页。
- WorkBuddy/CodeBuddy/Codex 任务、状态机和审查流程。

## 可信回测状态

`report_id=14`：155 trades、239 orders 全 mapped，trust audit 10/10 passed；total return 约 -19.29%。这不是策略稳定或实盘准入结论。

## 数据 Gate

- 全品种 1d：82 products passed、8 partial；176 assets passed、8 pending。
- pending 不得伪装完成：5 个 quality warning、3 个 actual-contract 缺 DB 登记。
- Stage 9 readiness 仍为 90 blocked，active audit 不授权发送。

## 运行与安全

- PostgreSQL/Redis 仅 localhost；Redis 环境变量认证。
- 开发脚本与生产模板分离。
- 公网模板强制 HTTPS、Basic Auth；FRP 只转发到 Mac mini 受监督的静态 Web/API，systemd 保留为 Linux 候选。
- 真实公网 smoke 尚未完成。
- macOS 外接卷 launchd 被系统权限阻断，失败 jobs 已卸载。

## 后续优先级

1. 真实服务器安全与恢复 smoke。
2. 8 个全品种 pending 独立修复。
3. 样本外 / walk-forward 验证设计。
4. macOS 外接卷后台权限或本机磁盘运行副本选择。

live scheduler、企业微信批量重试、自动归档、schema 语义拆分继续后置；自动交易继续禁止。
