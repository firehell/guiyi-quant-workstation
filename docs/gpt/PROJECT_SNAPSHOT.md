# PROJECT_SNAPSHOT.md

生成时间：2026-07-06
用途：上传到新的 ChatGPT 项目，作为“归一量化开发主控台”的长期项目上下文。
事实优先级：当前仓库代码最高，其次是 `CURRENT_STATE.md` / `PROJECT_SNAPSHOT.md`，再次是 `docs/ROADMAP.md`。早期聊天和旧文档只作为历史参考；若冲突，以当前代码和本轮状态文档为准。
敏感信息：本文不包含账号、密码、Token、API Key、交易密钥或 license。

## 1. 项目定位

归一量化是本地运行的国内期货量化研究、实时行情观察规划、策略信号提醒规划和 Web 复盘工作站。当前不是从零开始，而是在现有 MVP 上收敛重构。

V1 第一版围绕：

```text
数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号事件 -> 只读提醒 -> 复盘 -> 人工观察
```

项目不是公开 SaaS，不是普通展示网站，也不是无人值守自动实盘系统。V1 只做研究、回测、报告、信号提醒、人工观察和复盘闭环；信号只提醒，不自动下单。

## 2. 当前技术栈

| 层级 | 当前技术 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts |
| 后端 | Python 3.13、FastAPI、Pydantic、SQLAlchemy 2、Alembic |
| 队列 | Redis、RQ |
| 数据 | RQData、Local Standard Parquet、DuckDB、PostgreSQL |
| 回测 | vn.py / VeighNa CTA BacktestingEngine、自定义 Adapter / Runner / ResultConverter |
| 测试 | pytest、ruff、前端 build / node:test |
| 部署 | 本地 Mac / 本地工作站、Docker Compose、Cloudflare Access 作为后续远程访问方案 |

TqSdk / 天勤、TuShare、AKShare、CTP 字段只作为候选或历史占位，不是 V1 主链路。

## 3. 现有 MVP 可复用资产

现有能力应优先复用：

- FastAPI 后端和 Vue Web 工作台已经存在。
- RQData ingest、Parquet、DuckDB、PostgreSQL 数据链路已经有基础。
- vn.py CTA 回测底座、适配器、ResultConverter 和报告入库能力已经存在。
- Market K线、K线 marker、回测交易明细、复盘 note、信号扫描入口已经有可复用实现。
- 本地 `/healthz`、同源 API/WS 解析和 Cloudflare 访问文档已经形成准备项。

这些是“可复用资产”，不是实时 1m 入库、`signal_events`、企业微信提醒或 Web Market 策略展示已经全部完成的证明。

## 4. 当前主数据链路

当前 V1 active 数据入口只允许：

```text
source = rqdata / local_parquet
data_role = primary
quality_status != failed
```

严格研究优先使用 `quality_status=passed`。

旧 TqSdk / 天勤数据最多作为历史 validation source；交易练习者数据最多作为 legacy_reference。它们不得作为 V1 新建 active 数据入口，也不得绕过质量检查进入正式回测或信号输入。

## 5. 当前阶段状态

阶段 1 RQData 权限与接口能力 PoC 已完成，结论为 `PARTIAL`。

已确认：

- RQData import/auth 可用，`rqdatac` 版本为 `3.2.5`。
- JM 合约目录、DCE JM 合约列表、1d / 1m 小样本可用。
- 1m / 5m / 15m / 30m / 60m 返回字段包含 OHLCV 和 `open_interest`。
- 主力映射、合约乘数、保证金和手续费字段可用。

仍需后续确认：

- `trading_sessions`、`continuous_contracts`、`ex_factor` 返回 0 行。
- `realtime_snapshot_or_bar` 未验证。
- RQData PoC 不代表 JM 数据已更新，也不代表实时 1m 入库完成。

## 6. 当前目录结构

| 目录 | 作用 |
|---|---|
| `apps/quant-web/` | Vue Web 工作台 |
| `services/quant-api/` | FastAPI、ORM、任务、数据读取、回测、信号、复盘 API |
| `packages/quant-core/` | 策略共享包、vn.py CtaTemplate 策略 |
| `strategies/` | 策略说明目录 |
| `experiments/` | 隔离 PoC，不属于正式 V1 报告链路 |
| `data/` | 本地数据湖、manifest、质量报告 |
| `backtests/` | 本地导出报告和 review package |
| `docs/` | 架构、路线、验收、策略 spec、交接文档 |
| `tasks/` | Codex 任务管理 |
| `scripts/` | 启动、数据同步、审计、导出脚本 |

## 7. 当前核心模块

| 模块 | 关键代码 |
|---|---|
| API 入口 | `services/quant-api/app/main.py` |
| 数据中心 | `services/quant-api/app/api/data_center.py`、`app/data_sources/*`、`app/services/rqdata_ingest/*` |
| K线查询 | `services/quant-api/app/api/market.py`、`app/services/market_data_reader.py` |
| 回测任务 | `services/quant-api/app/api/backtests.py`、`app/backtest/v1b_jm_tasks.py`、`app/tasks/backtests.py` |
| vn.py 适配 | `services/quant-api/app/vnpy_integration/*` |
| 回测结果 | `services/quant-api/app/backtest/service.py`、`result_converter.py`、`report_metrics.py` |
| 信号扫描 | `services/quant-api/app/api/signals.py`、`app/signal/jm_v1b.py`、`app/services/signal_scanner.py` |
| 复盘中心 | `services/quant-api/app/api/reviews.py`、`app/review/backtest_trade.py` |
| Web 路由 | `apps/quant-web/src/app/router.ts` |
| K线组件 | `apps/quant-web/src/components/kline/KlineChart.vue`、`src/utils/tradeMarker.ts` |

## 8. 当前数据状态

JM 现有正式研究数据窗口仍需后续更新到最新交易日：

| 周期 | 范围 | 行数 | data_version |
|---|---|---:|---|
| 1d | 2023-01-03 至 2025-12-31 | 727 | `rqdata_jm_standard_1d_20230103_20251231_v1` |
| 15m | 2023-01-03 至 2025-12-31 | 16569 | `rqdata_jm_standard_15m_20230103_20251231_v1` |
| 5m | 2023-01-03 至 2025-12-31 | 49707 | `rqdata_jm_standard_5m_20230103_20251231_v1` |
| 1m | 2023-01-03 至 2025-12-31 | 248535 | `rqdata_jm_standard_1m_20230103_20251231_v1` |

阶段 2 才能在明确任务包、写入路径、manifest、checksum、quality_status、质量检查和回滚策略后更新 JM 数据。

## 9. 当前策略和回测状态

| 策略 | 版本 | 状态 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `v1b.0` | JM 15m / 5m 固定任务历史主线 |
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | 苏冰 JM 日线方向 + 15m/5m 短持有研究 spec |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 日线 EMA21 / MACD / 量能冻结基线 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.3.0-daily-score2of4` | 独立研究版本，trusted 结果为负 |

历史 V1-B / V1-Final 结果是可复用资产和回测口径参考，不是当前继续扩展自动交易的理由。

所有策略后续必须保持 `strategy_code`、`strategy_version`、参数、数据范围、数据源、`data_role`、`quality_status`、回测配置、信号来源和报告结果可追溯。

## 10. 当前未完成能力

以下是后续任务，不能写成已完成：

- JM 历史数据更新到最新交易日。
- manifest / checksum / quality_status 收敛。
- `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本原因确认。
- RQData 实时 1m 入库。
- 1m 聚合 5m / 15m / 30m / 1h / 1d / 1w。
- `signal_events` 信号事件化。
- 企业微信只读提醒。
- Web Market 策略展示、主图 marker、副图指标和策略切换。
- 本地长期运行、worker、scheduler、health check。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

## 11. 用户工作方式约束

用户通过 RemoteView 远程控制家中 Mac mini，Codex 在本地仓库执行任务。用户是兼职开发状态，后续任务应：

- 单功能域拆分。
- 每轮有明确允许和禁止修改范围。
- 高风险任务默认 Plan 模式或先审查。
- 输出可复制给 ChatGPT 的变更摘要和文件清单。
- 不依赖旧聊天作为当前事实。

## 12. 下一阶段建议

下一步进入：

```text
阶段 2：JM 历史数据更新到最新交易日的方案和执行任务
```

阶段 2 建议新 Codex 会话 + Plan 模式。先制定写入方案、数据范围、manifest / checksum、quality_status、质量检查和回滚策略，再运行任何写入命令。
