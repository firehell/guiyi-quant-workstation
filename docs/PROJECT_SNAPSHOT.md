# 归一量化项目现状快照

生成时间：2026-06-27  
工作区：`/Volumes/扩展盘/guiyi-quant-workstation`  
本次执行方式：只读检查，未修改代码，未执行迁移，未触碰 `.env` / `data/` / 实盘接口。

## 1. 项目一句话总结

归一量化是一个本地运行的国内期货量化研究工作站，当前 V1 聚焦“数据中心 → K线 → 策略 → vn.py 回测 → 报告 → 信号扫描 → 单笔复盘”的 Web 研究闭环。它不是 SaaS，不是自动交易平台，V1 明确不做实盘、不做自动下单、不接 CTP/TqSdk 交易接口。

## 2. Git 与工作区状态

当前分支：`main`

工作区状态：干净，`git status --short` 无输出。

最近提交显示项目已经推进到 V1 收尾：

- `d57441a test(v1): add refactor acceptance checklist`
- `6fbdb7c feat(review): create notes from backtest trades`
- `ac7f808 feat(signal): standardize strategy signal snapshots`
- `676109f feat(web): add backtest report detail and trade markers`
- `b87cbdf feat(web): add vnpy backtest task page`
- `4dc4fe7 feat(backtest): add backend e2e demo for vnpy sample path`

## 3. 架构现状

主链路与文档一致：

```text
RQData
→ raw/standard Parquet
→ DuckDB / MarketDataReader
→ vn.py adapter / result converter
→ PostgreSQL 业务事实库
→ FastAPI API / RQ worker
→ Vue Web 工作台
→ 回测报告 / 信号 / 复盘
```

核心目录：

- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api`：FastAPI、模型、API、任务、数据读取、vn.py 集成。
- `/Volumes/扩展盘/guiyi-quant-workstation/apps/quant-web`：Vue 3 Web 工作台。
- `/Volumes/扩展盘/guiyi-quant-workstation/packages/quant-core`：苏冰 EMA21 vn.py 策略草稿与配置。
- `/Volumes/扩展盘/guiyi-quant-workstation/experiments/vnpy_rqdata_demo`：后端最小 demo。
- `/Volumes/扩展盘/guiyi-quant-workstation/docs`：V1 路线、架构、数据、回测、验收文档。

## 4. 技术栈现状

后端实际依赖在 `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/pyproject.toml`：

- FastAPI、SQLAlchemy 2、Alembic、Redis/RQ、DuckDB、PyArrow、pandas、polars、pytest、ruff。
- `rqdatac` 保留为 V1 主数据源 SDK。
- `vnpy` 保留为 V1 CTA 回测底座。
- `tqsdk`、`tushare` 仍是默认依赖，但注释标记为 V2 candidate / legacy / auxiliary，不是 V1 主链路。

前端实际依赖在 `/Volumes/扩展盘/guiyi-quant-workstation/apps/quant-web/package.json`：

- Vue 3、Vite、TypeScript、Naive UI、Pinia、Vue Router、Axios、Lightweight Charts、ECharts/vue-echarts。

注意：Python 版本口径已在后续任务中统一为 Python 3.13；`pyproject.toml` 与 `uv.lock` 均使用 `requires-python >=3.13`。

## 5. 数据中心状态

已有模块：

- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/data_sources/`
- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/services/market_data_reader.py`
- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/services/rqdata_ingest/`
- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/services/tqsdk_ingest/`

已实现的关键规则：

- `DataRole` 包含 `primary`、`validation`、`legacy_reference`、`candidate`。
- 正式读取默认 `primary`。
- `LegacyDataProvider` 要求 validation / legacy_reference 必须显式选择。
- `MarketDataReader` 路径已支撑 Parquet + DuckDB 读取、coverage、quality status。
- TqSdk 旧模块仍在，但定位是 validation / V2 candidate。

缺口：

- 真实 RQData 批量下载、主力映射、交易参数、夜盘周期合成仍需要大样本验证。
- `.env.example` 仍包含早期 CTP/TqSdk/TuShare 占位项，口径上容易误导新 Agent。
- 当前本地 PostgreSQL schema 落后于模型，访问 `/api/backtests/tasks` 时出现 `backtest_tasks.engine_type` 缺列错误；本次未执行迁移。

## 6. vn.py 集成状态

已有模块：

- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/vnpy_integration/backtest_runner.py`
- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/vnpy_integration/result_converter.py`
- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/vnpy_integration/settings.py`
- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/vnpy_integration/strategy_loader.py`
- `/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/app/vnpy_integration/symbol_mapper.py`

当前能力：

- 可校验请求参数。
- 可检查 vn.py import。
- 可加载策略类路径。
- 可生成 vt_symbol 和 vn.py setting。
- 可把 raw result 转成标准 JSON。
- 未修改 vn.py 源码，未接 VeighNa Studio，未接实盘 gateway。

重要差距：

- `VnpyBacktestRunner.run()` 当前返回 `status=prepared`、`executed=False`。
- 也就是说，真实 vn.py `BacktestingEngine` 执行还没有接线。
- 这是后续进入“正式 vn.py 回测可运行链路”前最大的 P1 缺口。

## 7. 策略状态

已有策略：

- `/Volumes/扩展盘/guiyi-quant-workstation/packages/quant-core/guiyi_quant/strategies/su_bing_ema21/`
- `/Volumes/扩展盘/guiyi-quant-workstation/strategies/su_bing_ema21/`
- `/Volumes/扩展盘/guiyi-quant-workstation/strategies/ma_breakout/`
- `/Volumes/扩展盘/guiyi-quant-workstation/strategies/n_structure/`

苏冰 EMA21 已有：

- vn.py `CtaTemplate` 草稿。
- 参数 schema。
- 默认参数 JSON。
- 复盘标签 JSON。
- 测试覆盖配置合法性和避免未来 K 线依赖。

风险：

- 目前仍是草稿，实盘前必须做外部策略审查、样本外验证、成本/滑点/保证金验证。
- MA breakout 和 N structure 目前主要是文档/目录级占位。

## 8. 回测状态

已有能力：

- Backtest schema：`BacktestTaskConfig` 默认 `engine_type=vnpy`、`data_role=primary`。
- 禁止 `live` / `real` / `trading` / `auto_order` task type。
- 禁止 `quality_status=failed`。
- validation / legacy_reference 必须 `research_only=true`。
- RQ worker 函数：`run_backtest_task(task_id)`。
- API：任务创建/查询、报告查询、交易明细、资金曲线、回撤曲线。
- Web：回测任务页、报告详情页、K线 marker。

限制：

- 新 vn.py task runner 的 `persist_result()` 当前仍标记为 `task_payload_only`，正式 report/trade 表持久化还没有完全贯通到真实 vn.py runner。
- 旧/批量回测路径和报告模型存在，但 vn.py 正式执行链路还未完整闭环。
- 本地 DB 未应用最新 migration 时，API 会因缺列报错。

## 9. 前端状态

路由已覆盖：

- `/dashboard`
- `/data`
- `/market`
- `/strategy`
- `/backtest`
- `/backtest/batch`
- `/signal`
- `/review`
- `/settings`

已实现页面能力：

- 回测任务创建与状态查看。
- 回测报告指标、资金曲线、回撤曲线、交易明细、K线买卖点 marker。
- 信号扫描页展示信号解释，明确只观察不下单。
- 复盘页可从回测交易创建复盘备注。
- K线组件和图表组件已存在。

限制：

- 策略中心和系统设置仍偏壳子/早期状态。
- 前端依赖后端数据库迁移状态；本地 DB 不匹配会导致页面 API 失败。
- 没有自动下单按钮，这是符合边界的。

## 10. API 状态

OpenAPI 当前包含主要路由：

- `GET /api/health`
- `GET /api/v1/data/*`
- `GET /api/v1/market/*`
- `POST /api/backtests/tasks`
- `GET /api/backtests/tasks`
- `GET /api/backtests/reports`
- `GET /api/backtests/reports/{report_id}`
- `GET /api/backtests/reports/{report_id}/trades`
- `POST /api/signals/scan`
- `GET /api/signals/latest`
- `PATCH /api/signals/{signal_id}/status`
- `GET /api/reviews/*`
- `POST /api/reviews/from-backtest-trade/{trade_id}`
- `GET /api/watchlists`

注意：FastAPI 当前版本 route 对象中包含 `_IncludedRouter`，直接遍历 `app.routes` 不易看出展开路由；以 OpenAPI 结果为准。

## 11. 数据库和迁移状态

迁移文件存在到：

- `20260623_0001_data_center_v0.py`
- `20260624_0002_batch_backtest_v0.py`
- `20260624_0003_signal_scanner_v0.py`
- `20260624_0004_review_center_v0.py`
- `20260624_0005_rqdata_structured_ingest.py`
- `20260625_0006_market_data_file_symbol_unique.py`
- `20260625_0007_rqdata_contract_universe.py`
- `20260626_0008_vnpy_backtest_metadata.py`
- `20260626_0009_market_data_file_data_role.py`

本次没有执行迁移。实际本地 DB 至少缺 `backtest_tasks.engine_type`，说明本地数据库未到最新 schema。下一步若要启动 Web/API 演示，需要先由用户确认后执行 Alembic 升级或重建开发库。

## 12. 测试与质量结果

已运行：

```bash
uv run --project services/quant-api pytest -q
```

结果：`112 passed in 11.27s`

```bash
uv run --project services/quant-api ruff check .
```

结果：`All checks passed!`

```bash
cd apps/quant-web && pnpm build
```

结果：构建通过。

Demo：

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --check-env
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --sample
```

结果：均成功，输出到已忽略目录：

- `/Volumes/扩展盘/guiyi-quant-workstation/experiments/vnpy_rqdata_demo/output/environment_check.json`
- `/Volumes/扩展盘/guiyi-quant-workstation/experiments/vnpy_rqdata_demo/output/sample_standard_result.json`

## 13. 安全边界检查

敏感词扫描命中项主要是：

- 文档中的禁止事项说明。
- `.env.example` 的占位符。
- Docker / dev 脚本里的本地开发数据库默认口令。
- RQData/TqSdk client 从环境变量读取用户名密码。
- 前端 Axios 从 localStorage 读取 token。

未发现明显真实账号/API Key/交易密码。  
但 `.env.example` 和部分文档仍保留 CTP/TqSdk/TuShare 字段，建议单独清理为“V2 候选/禁用占位”，避免误导。

## 14. 已完成能力

当前代码已经具备：

- V1 文档主路线基本统一。
- RQData / local parquet / legacy 数据源抽象。
- data_role 隔离规则。
- vn.py adapter 骨架和 result converter。
- 苏冰 EMA21 vn.py 策略草稿。
- 回测任务 API 和 Web 页面。
- 回测报告详情页、交易表、资金/回撤曲线、K线 marker。
- 信号扫描后端与前端。
- 复盘中心从 backtest trade 创建 review note。
- V1 验收测试和 demo 命令。
- 自动实盘边界在 schema/API/文档中多处明确禁止。

## 15. 关键缺口

| 优先级 | 缺口 | 影响 |
|---|---|---|
| P0 | `/Volumes/扩展盘/guiyi-quant-workstation/tasks/current.md` 已严重过期 | 新 Codex 接手会被错误任务误导 |
| P0 | 本地 PostgreSQL 未应用最新 schema | Web/API 本地演示会报缺列 |
| P0 | Python 版本口径已统一为 Python 3.13 | 新环境应按 3.13 准备 |
| P1 | 真实 vn.py BacktestingEngine 尚未接线执行 | 目前还是 prepared/demo，不是正式 vn.py 回测 |
| P1 | vn.py runner 到 report/trade 表持久化未完全贯通 | Web 报告依赖样例/旧路径/预置数据 |
| P1 | 真实 RQData 数据下载与质量验证不足 | 回测结论不可用作正式研究依据 |
| P1 | 夜盘周期合成、主力映射、交易参数仍需验证 | 期货回测严谨性不足 |
| P2 | `.env.example` 仍有旧实盘/候选源字段 | 容易造成边界误解 |
| P2 | `tqsdk` / `tushare` 仍是默认依赖 | 安装语义不够干净 |
| P2 | 策略中心/系统设置仍偏壳子 | Web 闭环体验未完全产品化 |

## 16. 建议下一步

| 顺序 | 任务 | 修改范围建议 |
|---|---|---|
| 1 | 更新 `tasks/current.md` 和路线图状态 | 只改 docs/tasks |
| 2 | 对齐 Python 版本口径 | docs + pyproject 二选一决策 |
| 3 | 用户确认后处理本地 DB migration 状态 | 只执行/验证迁移，不写业务代码 |
| 4 | P1：接真实 vn.py BacktestingEngine 执行 | 只改 `services/quant-api/app/vnpy_integration/`、测试 |
| 5 | P1：打通 vn.py result → report/trade 持久化 | backtest service/model/API 测试 |
| 6 | P1：用小型标准 Parquet fixture 做正式 demo | experiments + tests |
| 7 | P2：清理 `.env.example` 与候选依赖说明 | docs + env example + dependency task |
| 8 | P2：真实 RQData 样本验收 | 数据中心专项，不碰实盘 |

## 17. 给 ChatGPT 的摘要

归一量化当前是本地国内期货量化研究工作站，V1 路线已统一为 RQData 主数据源、标准 Parquet 数据湖、DuckDB 查询、PostgreSQL 业务事实库、vn.py CTA 回测底座、FastAPI + Redis/RQ 后端、Vue 3 + Vite + Naive UI 自定义 Web。V1 明确不做自动实盘、不接 CTP/TqSdk 交易接口、不做自动下单、不修改 vn.py 源码。当前仓库工作区干净，后端测试 `112 passed`，ruff 通过，前端 `pnpm build` 通过，demo 的 `--check-env` 和 `--sample` 能跑通并输出标准 JSON。已完成数据源抽象、data_role 隔离、vn.py adapter 骨架、result converter、苏冰 EMA21 vn.py 策略草稿、回测任务 API/Web、报告页/K线 marker、信号扫描、复盘中心和 V1 验收测试。主要风险是：`tasks/current.md` 严重过期；本地 PostgreSQL 未应用最新迁移，访问回测任务 API 会缺 `backtest_tasks.engine_type`；真实 vn.py BacktestingEngine 尚未执行，只是 prepared/executed=false；真实 RQData 下载、主力映射、夜盘周期合成、交易参数和 report/trade 持久化仍需补齐。Python 版本口径已在后续任务中统一为 3.13。建议下一步先更新交接状态与 DB schema 状态，再小步接真实 vn.py 执行链路。
