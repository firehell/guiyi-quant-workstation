# PROJECT_SNAPSHOT.md

生成时间：2026-07-06
用途：上传到新的 ChatGPT 项目，作为“归一量化开发主控台”的长期项目上下文。
事实优先级：当前仓库代码最高，其次是 `CURRENT_STATE.md` / `PROJECT_SNAPSHOT.md`，再次是 `docs/ROADMAP.md`。早期聊天和旧文档只作为历史参考；若冲突，以当前代码和最新快照为准。
敏感信息：本文不包含账号、密码、Token、API Key、交易密钥或 license。

## 1. 项目定位

归一量化是本地运行的国内期货量化研究工作站，当前 V1 围绕：

```text
数据 -> K线 -> 策略 -> 回测 -> 报告 -> 信号 -> 复盘 -> 人工观察
```

项目不是公开 SaaS，不是普通展示网站，也不是无人值守自动实盘系统。V1 只做研究、回测、报告、信号提醒、人工观察和复盘闭环；信号扫描只提醒，不自动下单。

当前工程已不是从零设计阶段，而是进入 RQData 主链路加固、JM 数据更新、可信回测复核、本地工作站长期运行和 GPT/Codex 协作收敛阶段。

## 2. 当前技术栈

| 层级 | 当前技术 |
|---|---|
| 前端 | Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts |
| 后端 | Python 3.13、FastAPI、Pydantic、SQLAlchemy 2、Alembic |
| 队列 | Redis、RQ |
| 数据 | RQData、Local Standard Parquet、DuckDB、PostgreSQL |
| 回测 | vn.py / VeighNa CTA BacktestingEngine、自定义 Adapter / Runner / ResultConverter |
| 测试 | pytest、ruff、前端 build / node:test |
| 部署 | 本地 Mac / 本地工作站、Docker Compose、Cloudflare Tunnel + Access 浏览器访问 |

TqSdk / 天勤、TuShare、AKShare、CTP 字段只作为候选或历史占位，不是 V1 主链路。

## 3. 当前目录结构

| 目录 | 作用 | 当前状态 |
|---|---|---|
| `apps/quant-web/` | Vue Web 工作台 | 研究闭环页面已存在；同源 API/WS 解析支持远程浏览器访问 |
| `services/quant-api/` | FastAPI、ORM、任务、数据读取、回测、信号、复盘 API | V1 主链路基本可运行；新增 `/healthz` |
| `packages/quant-core/` | 策略共享包、vn.py CtaTemplate 策略 | 多个 JM / 苏冰策略版本并存 |
| `strategies/` | 策略说明性目录 | EMA21、均线突破、N 字结构方向保留 |
| `experiments/` | 隔离 PoC | RQAlpha / XMA 实验存在，但不属于正式 V1 报告链路 |
| `data/` | 本地数据湖、manifest、质量报告 | active 数据只允许 RQData / Local Standard Parquet primary 链路 |
| `backtests/` | 本地导出报告和 review package | 有历史报告与导出包，不等同于当前数据库事实 |
| `docs/` | 架构、路线、验收、策略 spec、交接文档 | 当前同步入口是 `CURRENT_STATE.md`、`PROJECT_SNAPSHOT.md`、`docs/CODEX_HANDOFF_FOR_CHATGPT.md` |
| `tasks/` | Codex 任务管理 | `tasks/current.md` 当前记录本次 GPT 同步包更新 |
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
| 远程访问 | `apps/quant-web/src/utils/network.ts`、`docs/CLOUDFLARE_WORKSTATION_ACCESS.md` |

## 5. 当前已经完成的能力

- RQData / Local Standard Parquet 作为 V1 主数据源口径已经确立。
- DATA-001 已完成：旧天勤数据、交易练习者数据和 TqSdk 临时下载文件已从 active 数据体系移除。
- 默认正式读取只允许 `source=rqdata/local_parquet`、`data_role=primary`、`quality_status!=failed`。
- JM 最近 3 年 1d / 15m / 5m / 1m 数据资产已形成。
- vn.py CTA 回测底座已接入，支持固定 JM 回测任务和日线策略任务。
- 回测报告、交易明细、订单、资金曲线、回撤曲线 API 已存在。
- Web 有 Dashboard、Data、Market、Strategy、Backtest、Signal、Review、Settings 路由。
- K线上已有交易 marker 相关工具和页面联动代码。
- 可以从 backtest trade 创建 review note。
- 信号扫描提醒能力存在，但 V1 只提醒不下单。
- 本地工作站已补 `/healthz` 和 Cloudflare Tunnel + Access 配置文档，方便远程浏览器访问。

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

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:5173/healthz
```

关键页面：

```text
http://127.0.0.1:5173/data
http://127.0.0.1:5173/market
http://127.0.0.1:5173/backtest
http://127.0.0.1:5173/signal
http://127.0.0.1:5173/review
```

远程浏览器访问口径见 `docs/CLOUDFLARE_WORKSTATION_ACCESS.md`。

## 7. 当前主要策略

| 策略 | 版本 | 状态 |
|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `v1b.0` | JM 15m / 5m 固定任务主线，V1-Final 验收报告已生成 |
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | 苏冰 JM 日线方向 + 15m/5m 短持有策略包，主要用于 spec 和研究 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 日线 EMA21 / MACD / 量能冻结基线 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.3.0-daily-score2of4` | 独立研究版本，任意 2/4 条件加方向锚点，trusted 结果为负 |
| `su_bing_ema21` | 草稿 / 共享方向 | EMA21 策略草稿和知识沉淀 |

所有策略后续必须保持 `strategy_code`、`strategy_version`、参数、数据范围、回测配置、报告结果可追溯。

## 8. 当前数据状态

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

严格研究优先使用 `quality_status=passed`。

## 9. 当前回测和策略结论

- V1-Final 15m / 5m 报告：`report_id=5` / `report_id=6`，历史验收通过，但不代表实盘收益。
- `v0.2.0-daily` baseline 不得静默修改。
- `v0.3.0-daily-score2of4` 报告：`report_id=11`。
- `v0.3` raw 为正，但 trusted excluding cross-contract 为负：
  - raw trades：47
  - trusted trades：39
  - excluded cross-contract trades：8
  - raw net pnl：52798.083
  - trusted net pnl：-34914.555
  - trusted max consecutive losses：8
- 当前不应进入模拟盘、实盘、自动下单或多品种参数优化。

## 10. 当前未完成问题

- JM 数据仍需更新到最新可用交易日。
- RQData 接口能力、字段覆盖、限制和错误类型需要只读 PoC 清单。
- manifest / checksum / quality_status 需要进一步收敛。
- RQData 实时 1m 入库、1m 聚合、signal_events、企业微信只读提醒、长期运行 health check 仍是后续任务。
- Data / Market / Signal / Review 页面浏览器 smoke 仍需单独执行。
- Dashboard 仍可能是 mock；Strategy / Settings 与后端接口一致性需要后续验收。
- rollover / cross-contract PnL 仍需独立关闭，可信结论不能混入跨合约收益。

## 11. 下一阶段建议

1. 新 Codex 会话 + Plan 模式执行“RQData 权限与接口能力 PoC”。
2. PoC 只读，不写 `data/`，不写数据库，不打印 licence。
3. PoC 通过后，再设计 JM 历史数据更新到最新交易日、manifest / checksum / quality_status 收敛。
4. 实时 1m 入库、企业微信提醒、worker/scheduler、可信回测复核都应拆成独立任务，不要顺手扩展。
