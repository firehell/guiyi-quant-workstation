# PROJECT_SNAPSHOT.md

生成时间：2026-06-30，最近更新：2026-06-30 文档入口清理后
用途：上传到新的 ChatGPT 项目，作为“归一量化开发主控台”的长期项目上下文。  
事实优先级：当前仓库代码最高，其次是 `PROJECT_SNAPSHOT.md` / `CURRENT_STATE.md`，再次是 `docs/ROADMAP.md`。早期聊天和旧文档只作为历史参考；若冲突，以当前代码和最新快照为准。  
敏感信息：本文不包含账号、密码、Token、API Key、交易密钥或 license。

## 1. 项目定位

归一量化是本地运行的国内期货量化研究工作站，当前第一版围绕：

```text
数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号 -> 复盘
```

项目不是公开 SaaS，不是普通展示网站，也不是无人值守自动实盘系统。V1 只做研究、回测、报告、信号提醒、人工观察和复盘闭环；信号扫描只提醒，不自动下单。

当前工程已不是从零设计阶段，而是进入焦煤 JM 真实数据策略优化、回测验证、可信指标审查和后续任务编排阶段。

## 2. 当前技术栈

| 层级 | 当前技术 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts |
| 后端 | Python 3.13、FastAPI、Pydantic、SQLAlchemy 2、Alembic |
| 队列 | Redis、RQ |
| 数据 | RQData、Local Standard Parquet、DuckDB、PostgreSQL |
| 回测 | vn.py / VeighNa CTA BacktestingEngine、自定义 Adapter / Runner / ResultConverter |
| 测试 | pytest、ruff、mypy 预留、前端 build / 指标测试 |
| 部署 | 本地 Mac / 本地工作站、Docker Compose，不上云 |

TqSdk / 天勤、TuShare、AKShare、CTP 字段只作为候选或历史占位，不是 V1 主链路。

## 3. 当前目录结构

| 目录 | 作用 | 当前状态 |
|---|---|---|
| `apps/quant-web/` | Vue Web 工作台 | 页面骨架和核心页面已存在，回测/K线/信号/复盘可用，Dashboard/Strategy/Settings 仍有壳子或接口风险 |
| `services/quant-api/` | FastAPI、ORM、任务、数据读取、回测、信号、复盘 API | V1 主链路基本可运行 |
| `packages/quant-core/` | 策略共享包、vn.py CtaTemplate 策略 | 多个 JM / 苏冰策略版本并存 |
| `strategies/` | 策略说明性目录 | EMA21、均线突破、N 字结构方向保留 |
| `data/` | 本地数据湖、manifest、质量报告 | 含正式 RQData / primary 数据，也有 validation / legacy_reference，必须隔离 |
| `backtests/` | 本地导出报告和 review package | 有历史报告与导出包，不等同于当前数据库事实 |
| `docs/` | 架构、路线、验收、策略 spec、交接文档 | 已整理旧 ChatGPT / Codex 入口，当前入口集中到新上下文包和 `docs/AI_DEVELOPMENT_WORKFLOW.md` |
| `tasks/` | Codex 任务管理 | `tasks/current.md` 仍是上一轮 score2of4 任务记录，下一轮业务任务前需更新 |
| `scripts/` | 启动、数据同步、审计、导出脚本 | 可支撑本地开发和数据审计 |

## 4. 当前核心模块

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

## 5. 当前已经完成的功能

- RQData / local standard Parquet 作为 V1 主数据源口径已经确立。
- JM 最近 3 年 1d / 15m / 5m / 1m 数据资产已形成，正式回测默认应使用 primary / passed 数据。
- vn.py CTA 回测底座已接入，支持固定 JM 回测任务和日线策略任务。
- 回测报告、交易明细、订单、资金曲线、回撤曲线 API 已存在。
- Web 有 Dashboard、Data、Market、Strategy、Backtest、Signal、Review、Settings 路由。
- K线上已有交易 marker 相关工具和页面联动代码。
- 可以从 backtest trade 创建 review note。
- JM V1-Final 15m / 5m 真实交易约束闭环曾通过验收，报告 `report_id=5` / `report_id=6`。
- 2026-06-30 新增 `v0.3.0-daily-score2of4` 日线研究版本，报告 `report_id=11`，已输出 raw 和 trusted excluding cross-contract 指标。
- 2026-06-30 已整理新 ChatGPT 项目长期上下文包，并删除旧入口文档 `docs/AI_WORKFLOW.md`、`docs/CODEX_PROMPT_TEMPLATE.md`、`docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`、`docs/PROJECT_PROGRESS.md`。

## 6. 当前可运行能力

常用启动方式：

```bash
./scripts/dev-up.sh
./scripts/dev-down.sh
```

后端手动启动：

```bash
cd services/quant-api
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端手动启动：

```bash
cd apps/quant-web
pnpm dev --host 127.0.0.1 --port 5173
```

关键页面：

```text
http://127.0.0.1:5173/backtest
http://127.0.0.1:5173/market
http://127.0.0.1:5173/signal
http://127.0.0.1:5173/review
```

当前可上传给新 ChatGPT 项目的长期上下文文件：

- `PROJECT_SNAPSHOT.md`
- `CURRENT_STATE.md`
- `docs/CODEX_HANDOFF_FOR_CHATGPT.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `docs/ROADMAP.md`

关键 API：

- `POST /api/backtests/tasks`
- `POST /api/backtests/v1b/jm/15m/tasks`
- `POST /api/backtests/v1b/jm/5m/tasks`
- `POST /api/backtests/v1b/jm/daily-ema21-macd-volume/tasks`
- `POST /api/backtests/v1b/jm/daily-score2of4/tasks`
- `GET /api/backtests/reports`
- `GET /api/backtests/reports/{report_id}/trades`
- `POST /api/signals/v1b/jm/scan?run_inline=true`
- `POST /api/reviews/from-backtest-trade/{trade_id}`

## 7. 当前主要策略

| 策略 | 版本 | 状态 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `v1b.0` | JM 15m / 5m 固定任务主线，V1-Final 验收报告已生成 |
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | 苏冰 JM 日线方向 + 15m/5m 短持有策略包，主要用于 spec 和研究 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 日线 EMA21 / MACD / 量能冻结基线 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.3.0-daily-score2of4` | 2026-06-30 独立研究版本，任意 2/4 条件加方向锚点 |
| `su_bing_ema21` | 草稿 / 共享方向 | EMA21 策略草稿和知识沉淀 |

所有策略后续必须保持 `strategy_code`、`strategy_version`、参数、数据范围、回测配置、报告结果可追溯。

## 8. 当前回测能力

- 正式路线是 RQData / Local Parquet -> DuckDB -> vn.py CTA BacktestingEngine -> ResultConverter -> PostgreSQL -> Web。
- 回测结果必须记录数据来源、数据角色、质量状态、策略版本、参数、成本、滑点、合约乘数、保证金、最大回撤、连续亏损。
- 回测相关结论必须默认检查未来函数、数据泄露和过拟合。
- 当前仍有旧自研 `/api/backtests/run` 路径和 prepared-only 能力，后续应明确正式入口，避免混淆。
- 对跨合约交易，必须区分 raw metrics 和 trusted excluding cross-contract metrics。

## 9. 当前 Web 展示能力

- `/backtest`：报告列表、报告详情、交易明细、订单、资金/回撤数据、导出能力。
- `/market`：K线图、周期选择、report marker 关联能力。
- `/signal`：信号扫描和最新信号展示能力。
- `/review`：复盘 note 列表、从回测交易创建复盘。
- `/data`：数据中心页面。
- `/dashboard`：存在但后端 summary 仍可能是 mock。
- `/strategy` 与 `/settings`：页面存在，但与后端接口的一致性需后续验收。

## 10. 当前数据状态

JM 正式研究数据范围：

| 周期 | 范围 | 行数 | data_version |
|---|---|---:|---|
| 1d | 2023-01-03 至 2025-12-31 | 727 | `rqdata_jm_standard_1d_20230103_20251231_v1` |
| 15m | 2023-01-03 至 2025-12-31 | 16569 | `rqdata_jm_standard_15m_20230103_20251231_v1` |
| 5m | 2023-01-03 至 2025-12-31 | 49707 | `rqdata_jm_standard_5m_20230103_20251231_v1` |
| 1m | 2023-01-03 至 2025-12-31 | 248535 | `rqdata_jm_standard_1m_20230103_20251231_v1` |

正式回测默认只使用：

```text
source = rqdata / local_parquet
data_role = primary
quality_status != failed
```

旧天勤数据只可作为 validation source；交易练习者数据只可作为 legacy_reference。

## 11. 当前未完成问题

- `tasks/current.md` 当前记录的是上一轮 score2of4 任务，不是本轮长期上下文包任务。
- 旧 ChatGPT / Codex 入口文档已清理，但部分历史阶段文档仍保留为参考；后续应以本文件、`CURRENT_STATE.md` 和当前代码为准。
- `v0.3.0-daily-score2of4` trusted 指标为负，不能作为实盘或模拟盘依据。
- rollover / cross-contract PnL 仍需独立关闭，可信结论不能混入跨合约收益。
- Strategy/Settings/Dashboard 仍需 Web/API 一致性验收。
- worker 非 inline、scheduler、浏览器 smoke、Alembic current 需要在相关任务中复核。

## 12. 当前风险点

- 回测结果不等于实盘结果，任何正收益都不能直接转为下单规则。
- JM 单品种、特定窗口存在过拟合风险。
- 日线方向、15m/5m 入场、next bar open 成交必须持续检查未来函数和数据泄露。
- 跨合约交易如未强制退出或剔除，会污染收益判断。
- 多策略版本并存，后续必须冻结 spec 后再优化，不能静默修改旧版本参数。
- 不能把 TqSdk / CTP / 实盘字段误认为 V1 当前主链路。

## 13. 下一阶段建议

1. 先做 `v0.3.0-daily-score2of4` 可信指标复核和规则收敛，不进入实盘。
2. 优先关闭 rollover-safe / cross-contract P0：生成不混入跨合约 PnL 的正式可信报告。
3. 做条件组合消融：重点限制 `score=2`、`volume_only_confirm`、`range_risk`、`no_macd_cross`。
4. 若继续日线版本，必须新建 `strategy_version`，例如 `v0.3.1-*`，不得改写 `v0.2.0-daily` 或 `v0.3.0-daily-score2of4` 的历史行为。
5. 若回到 V1-B 主线，则优先验证“日线只定方向，15m/5m 独立入场，短持有 5-8 根”的策略效果和报告口径。
6. 每轮 Codex 任务前先更新 `tasks/current.md` 或提供等价任务包，明确允许/禁止文件、Gate、测试命令和 final 输出格式。
7. 新 ChatGPT 项目应优先读取新上下文包，不再读取已删除的旧入口文档。
