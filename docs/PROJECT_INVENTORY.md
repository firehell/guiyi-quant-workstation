# 归一量化工作站目录与功能清单

生成时间：2026-07-07

## 1. 当前事实源

优先阅读：

1. `README.md`
2. `tasks/current.md`
3. `docs/gpt/CURRENT_STATE.md`
4. `docs/gpt/PROJECT_SNAPSHOT.md`
5. `docs/gpt/NEXT_STEPS.md`
6. `docs/ARCHITECTURE.md`
7. `docs/DATA_CENTER.md`
8. `docs/BACKTEST_ENGINE.md`
9. `docs/STRATEGY_CURRENT_STATE.md`

## 2. 顶层目录

| 路径 | 作用 |
|---|---|
| `apps/quant-web/` | Vue 3 Web 工作台 |
| `services/quant-api/` | FastAPI 后端、RQ worker、ORM、API、WebSocket |
| `packages/quant-core/` | vn.py CtaTemplate 策略和共享配置 |
| `strategies/` | 策略说明目录 |
| `data/` | raw / standard parquet、manifest、质量报告 |
| `docs/` | 当前事实源、架构、数据、回测、策略、交接 |
| `scripts/` | 启停、RQData、审计、导出脚本 |
| `experiments/` | 隔离 PoC，不属于正式 V1 报告链路 |
| `tasks/` | 当前任务和任务队列 |
| `prompts/` | AI 提示模板 |

## 3. Web 工作台

技术栈：Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts。

| 页面 | 路由 | 状态 |
|---|---|---|
| Dashboard | `/dashboard` | 占位，真实数据未接入 |
| Data | `/data` | 数据中心页面，下一步需要 JM v2 smoke |
| Market | `/market` | K 线、指标、marker |
| Strategy | `/strategy` | 占位，待实用化 |
| Backtest | `/backtest` | 回测任务、报告、曲线、明细 |
| Batch Backtest | `/backtest/batch` | watchlist 批量回测、WebSocket 进度 |
| Signal | `/signal` | JM V1-B 扫描，只提醒不下单 |
| Review | `/review` | 复盘 note、标签、统计 |
| Settings | `/settings` | 占位，待持久化 |

关键文件：

- `apps/quant-web/src/app/router.ts`
- `apps/quant-web/src/pages/data/index.vue`
- `apps/quant-web/src/pages/market/index.vue`
- `apps/quant-web/src/pages/backtest/index.vue`
- `apps/quant-web/src/pages/signal/index.vue`
- `apps/quant-web/src/pages/review/index.vue`
- `apps/quant-web/src/components/kline/KlineChart.vue`

## 4. 后端 API

技术栈：Python 3.13、FastAPI、SQLAlchemy 2、Alembic、Redis/RQ、DuckDB、vn.py。

| 模块 | 关键文件 | 状态 |
|---|---|---|
| API 入口 | `services/quant-api/app/main.py` | 已挂载 REST / WS / health |
| 数据中心 | `app/api/data_center.py`、`app/services/rqdata_ingest/*` | 已有 RQData ingest 和质量登记 |
| Market | `app/api/market.py`、`app/services/market_data_reader.py` | 已有 K 线读取 |
| Backtest | `app/api/backtests.py`、`app/backtest/*` | 已有 vn.py 任务和报告 |
| Signal | `app/api/signals.py`、`app/signal/jm_v1b.py` | 已有 JM V1-B 扫描 |
| Review | `app/api/reviews.py`、`app/review/backtest_trade.py` | 已有复盘 note |
| WebSocket | `app/websocket/*` | 已有 backtest / signal 通道 |

## 5. 数据资产

当前 JM v2 数据：

```text
1m / 5m / 15m / 30m / 60m / 1d
20230103_20260707_v2
provider=rqdata
data_role=primary
quality_status=passed
```

关键证据：

- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

## 6. 策略与实验

正式策略代码在 `packages/quant-core/guiyi_quant/strategies/`。

保留的策略文档事实源：

- `docs/strategy_specs/*/STRATEGY_TARGET.md`
- `docs/strategy_specs/*/STRATEGY_SPEC.md`
- `docs/strategy_specs/*/STRATEGY_SPEC_REVIEW.md`
- `docs/strategy_specs/*/BACKTEST_REVIEW_CONTEXT.md`

`experiments/` 只作为隔离 PoC，不入 PostgreSQL，不等同于正式可信回测报告。

## 7. 已具备功能

- 数据中心、RQData ingest、JM v2 parquet / manifest / quality 登记。
- DuckDB 读取 standard parquet。
- Market K 线查询、指标和买卖点 marker。
- vn.py CTA 回测任务、JM V1-B 固定任务、报告、曲线、交易明细。
- 批量回测 watchlist 和 WebSocket 进度。
- JM V1-B 信号扫描，只提醒不下单。
- `signal_events` 信号事件化。
- 从回测成交创建复盘 note、标签和统计。
- 健康检查：`/health`、`/api/health`、`/healthz`。

## 8. 未完成能力

- RQData 实时 1m 入库。
- 1m 聚合多周期。
- 企业微信只读提醒。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 本地长期运行、worker、scheduler、health check 完整验收。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

## 9. 删除和清理口径

本轮强清理删除了：

- 过期 PoC 交接文档。
- 旧 RQData-only 路线文档。
- 策略中间 handoff、旧设计、旧审计和重复 review。
- `.DS_Store`、`__pycache__`、pytest / ruff 缓存。
- `experiments/*/output/*` 可再生成结果文件。

未删除：

- 当前 JM v2 数据证据。
- manifest。
- Parquet / processed 数据。
- 业务代码。
- 测试。
- 当前策略事实源。
