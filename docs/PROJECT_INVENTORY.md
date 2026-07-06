# 归一量化工作站 — 当前功能与目录说明

> 用途：给新接手开发者、Agent 或外部审查快速了解仓库结构与各文件职责。  
> 当前状态入口：以根目录 [`CURRENT_STATE.md`](../CURRENT_STATE.md)、[`PROJECT_SNAPSHOT.md`](../PROJECT_SNAPSHOT.md) 和 [`CODEX_HANDOFF_FOR_CHATGPT.md`](CODEX_HANDOFF_FOR_CHATGPT.md) 为准。
> 最后更新：2026-07-06

---

## 一、项目定位与当前阶段

**归一量化**是本地运行的国内期货量化研究、回测、复盘、信号扫描工作台，**不做自动实盘、不自动下单**。

主链路：

```text
RQData 米筐
→ raw parquet
→ standard parquet
→ PostgreSQL 元数据 + DuckDB 查询
→ vn.py BacktestingEngine
→ 回测报告 / 交易明细 / 曲线
→ FastAPI
→ Vue Web 工作台
→ 复盘 note / 信号扫描提醒
```

**已实现的核心业务能力**（按模块）：

| 模块 | 状态 | 说明 |
|------|------|------|
| 数据中心 | 已实现 | RQData 同步、Parquet 标准化、质量报告、Web 展示 |
| K 线工作台 | 已实现 | 多周期 K 线、EMA/MACD/ATR、回测买卖点 marker |
| 回测中心 | 已实现 | vn.py 任务、JM V1-B 固定任务、报告/曲线/明细 |
| 批量回测 | 已实现 | watchlist 多品种、WebSocket 进度（侧栏无入口） |
| 信号扫描 | 已实现 | JM V1-B 专用扫描、只提醒不下单 |
| 复盘中心 | 已实现 | 从回测成交创建 note、标签、统计 |
| 本地工作站访问 | 已实现基础 | `/healthz`、同源 API/WS、Cloudflare Tunnel + Access 文档 |
| 仪表盘 | 占位 | mock 数据，未接 API |
| 策略管理 | 占位 | 空表格 |
| 系统设置 | 占位 | 表单未持久化 |
| 实盘/CTP | 未做 | V1 明确不做 |

**当前数据源状态**：

- active 数据入口只允许 `rqdata` / `local_parquet` + `primary` + `quality_status != failed`。
- 旧 TqSdk / 天勤、交易练习者数据和 TqSdk 临时下载文件已从 active 数据体系移除。
- RQAlpha / XMA 目录属于隔离 PoC，不属于正式 V1 回测报告链路。

**vn.py 执行状态（与代码一致）**：

- `VnpyBacktestRunner.run()` 在 `prepared_only=false`（RQ Worker 默认路径）时会真实调用 vn.py `BacktestingEngine`，返回 `executed=true`。
- `prepared_only=true` 时仅返回准备态（`executed=false`），用于配置校验与测试。
- JM V1-B 15m / 5m 正式报告（`report_id=3/4`）已通过该链路入库。

---

## 二、仓库根目录文件

| 文件/目录 | 功能 |
|-----------|------|
| [`AGENTS.md`](../AGENTS.md) | AI Agent 协作规范、V1 路线、禁止事项（必读） |
| [`CLAUDE.md`](../CLAUDE.md) | 兼容入口，指向 AGENTS.md 与交接文档 |
| [`README.md`](../README.md) | 项目简介、快速导航、本地启动命令 |
| [`CURRENT_STATE.md`](../CURRENT_STATE.md) | 当前仓库状态速览 |
| [`PROJECT_SNAPSHOT.md`](../PROJECT_SNAPSHOT.md) | 给 GPT 的长期项目快照 |
| [`docker-compose.yml`](../docker-compose.yml) | 启动 PostgreSQL 16 + Redis 7（应用层在宿主机跑） |
| [`.env.example`](../.env.example) | 环境变量模板（RQData、DB、Redis、风控参数等） |
| [`.env`](../.env) | 本地实际配置（**不入库**） |
| [`.gitignore`](../.gitignore) | Git 忽略规则 |
| [`.vscode/`](../.vscode/) | VS Code / Cursor 编辑器配置 |
| [`.run/`](../.run/) | `dev-up.sh` 运行时 PID 与日志（`dev/`、`logs/`） |
| [`.pytest_cache/`](../.pytest_cache/) | pytest 缓存 |
| [`.ruff_cache/`](../.ruff_cache/) | ruff linter 缓存 |

---

## 三、顶层目录总览

```text
guiyi-quant-workstation/
├── apps/           Vue 3 前端
├── services/       FastAPI 后端
├── packages/       共享策略库 quant-core
├── strategies/     策略文档占位（规则说明）
├── data/           本地数据湖（raw / parquet / processed）
├── backtests/      回测输出目录（reports/、results/，当前空）
├── docs/           设计/进度/协作文档
├── scripts/        开发启停 + 数据同步脚本
├── experiments/    隔离实验 demo
├── tasks/          当前任务与任务队列目录
├── prompts/        AI 提示词模板
├── screenshots/    UI 截图存档
├── .cursor/        Cursor IDE 规则
├── .agents/        Agent 领域技能包
└── .codex/         Codex 审查 Agent 配置
```

---

## 四、[`apps/quant-web/`](../apps/quant-web/) — Vue 3 前端

技术栈：Vue 3.5 + Vite 8 + TypeScript + Naive UI + Lightweight Charts + ECharts + Pinia + Axios。

### 根级文件

| 文件 | 功能 |
|------|------|
| `package.json` / `pnpm-lock.yaml` | 依赖与 lock |
| `vite.config.ts` | 开发服务器 5173、代理 `/api` 和 `/ws` 到 8000 |
| `index.html` | Vite HTML 入口 |
| `tsconfig*.json` | TypeScript 配置 |
| `README.md` | 默认 Vite 模板说明 |
| `public/icons.svg` | 静态图标 |

### [`src/`](../apps/quant-web/src/) 源码

**入口与布局**

| 文件 | 功能 |
|------|------|
| `main.ts` | 挂载 Pinia、Router |
| `App.vue` | 根组件，Naive UI 深色主题 |
| `style.css` | 全局样式 |
| `app/router.ts` | 9 条路由定义（含批量回测子路由） |
| `app/pinia.ts` | Pinia 初始化 |
| `layouts/MainLayout.vue` | 侧边栏 + 顶栏 + 内容区 |

**页面 [`pages/`](../apps/quant-web/src/pages/)**

| 文件 | 路由 | 功能 | 成熟度 |
|------|------|------|--------|
| `dashboard/index.vue` | `/dashboard` | 4 个统计卡片 | 占位 |
| `data/index.vue` | `/data` | 数据源/品种/合约/任务/质量报告 Tab | 已对接 |
| `market/index.vue` | `/market` | K 线工作台、指标、买卖点 marker、策略状态 | 核心 |
| `strategy/index.vue` | `/strategy` | 策略列表空表格 | 占位 |
| `backtest/index.vue` | `/backtest` | 创建回测、报告/曲线/明细、K 线联动 | 核心 |
| `backtest/batch.vue` | `/backtest/batch` | 批量回测、WS 进度、结果对比 | 核心 |
| `signal/index.vue` | `/signal` | JM V1-B 扫描、信号分级、WS+轮询 | 核心 |
| `review/index.vue` | `/review` | 复盘 CRUD、标签、统计、K 线 marker | 核心 |
| `settings/index.vue` | `/settings` | API/WS 地址、涨跌色设置 | 占位 |

**API 层 [`api/`](../apps/quant-web/src/api/)**

| 文件 | 功能 |
|------|------|
| `request.ts` | Axios 单例、token 拦截、baseURL 处理 |
| `data.ts` | `/api/v1/data/*` 数据中心 |
| `market.ts` | `/api/v1/market/*`、legacy `/api/klines` |
| `backtestApi.ts` | vn.py 回测任务与报告 REST |
| `strategy.ts` | watchlist、批量回测、legacy `/run` |
| `signal.ts` | 信号扫描 API |
| `review.ts` | 复盘中心 API |

**组件 [`components/`](../apps/quant-web/src/components/)**

| 文件 | 功能 |
|------|------|
| `kline/KlineChart.vue` | Lightweight Charts 主图：K 线、成交量、EMA、MACD/ATR、marker |
| `charts/BaseChart.vue` | ECharts 通用封装（资金/回撤曲线） |
| `charts/LineChart.vue` / `BarChart.vue` | 细分图表封装 |
| `tables/DataTable.vue` | Naive UI 表格薄封装 |
| `common/StatusTag.vue` | 运行状态标签 |
| `common/EmptyState.vue` | 空状态 |

**其他**

| 目录/文件 | 功能 |
|-----------|------|
| `stores/app.ts` | 侧栏折叠、主题、apiBaseUrl（页面几乎未用） |
| `stores/strategy.ts` | 策略列表缓存（几乎未用） |
| `stores/signal.ts` | 信号列表缓存（几乎未用） |
| `types/*.ts` | 各域 TypeScript 类型 |
| `utils/indicators.ts` | 前端 EMA/ATR/MACD 计算 |
| `utils/format.ts` | 金额/百分比格式化 |
| `utils/constants.ts` | 交易所、周期、ECharts 默认配置 |
| `websocket/WsClient.ts` | 自动重连 WebSocket 客户端 |
| `websocket/index.ts` | 全局 WS、`subscribeSignals` 等 |
| `tests/indicators.test.ts` | 指标单元测试 |

---

## 五、[`services/quant-api/`](../services/quant-api/) — FastAPI 后端

技术栈：Python 3.13、FastAPI、SQLAlchemy 2、Alembic、Redis/RQ、vn.py、DuckDB、pytest。

### 根级文件

| 文件 | 功能 |
|------|------|
| `pyproject.toml` / `uv.lock` | 依赖管理 |
| `README.md` | 当前为空 |
| `alembic.ini` | Alembic 配置 |

### [`app/main.py`](../services/quant-api/app/main.py)

FastAPI 入口：挂载 5 组 REST router、2 组 WebSocket、健康检查、仪表盘 mock。

### [`app/api/`](../services/quant-api/app/api/) — REST 路由

| 文件 | 前缀 | 功能 |
|------|------|------|
| `data_center.py` | `/api/v1/data` | 数据源、交易所、品种、合约、下载任务、质量报告、coverage；兼容 `/api/symbols`、`/api/klines` |
| `market.py` | `/api/v1/market` | K 线工作台 coverage、bars（支持 `data_role`） |
| `backtests.py` | `/api/backtests` | 创建 vn.py 任务、JM V1-B 固定任务、legacy 同步回测、报告/曲线/明细、watchlist |
| `signals.py` | `/api/signals` | 通用/JM V1-B 扫描、latest、ack/status |
| `reviews.py` | `/api/reviews` | 复盘 CRUD、从回测成交创建、标签、统计、附件 |

### [`app/backtest/`](../services/quant-api/app/backtest/) — 回测领域

| 文件 | 功能 |
|------|------|
| `service.py` | 任务创建、vn.py setting 生成、报告持久化 |
| `runner.py` | RQ worker 执行：VnpyBacktestRunner + result_converter |
| `engine.py` | 自研苏冰 EMA21 bar 级 engine（legacy `/run` 路径） |
| `specs.py` | 回测规格/配置结构 |
| `contract_resolver.py` | 合约解析 |
| `v1b_jm_tasks.py` | JM V1-B 固定任务 builder（15m/5m） |

### [`app/vnpy_integration/`](../services/quant-api/app/vnpy_integration/) — vn.py 适配

| 文件 | 功能 |
|------|------|
| `backtest_runner.py` | 封装 vn.py BacktestingEngine |
| `strategy_loader.py` | 动态加载 quant-core 策略 |
| `symbol_mapper.py` | 归一 symbol ↔ vn.py vt_symbol |
| `execution_policy.py` | 信号 bar → 成交 bar 时点（防未来函数） |
| `result_converter.py` | vn.py 原始结果 → 归一标准报告 |
| `settings.py` | `require_vnpy()` 运行时检测 |
| `smoke_strategy.py` | 冒烟测试用最小策略 |
| `errors.py` | vn.py 集成错误类型 |

### [`app/data_sources/`](../services/quant-api/app/data_sources/) — 行情读取抽象

| 文件 | 功能 |
|------|------|
| `base.py` | `MarketDataProvider` 抽象接口 |
| `local_parquet_provider.py` | 本地标准 Parquet（V1 默认） |
| `rqdata_provider.py` | 米筐实时/补充读取 |
| `providers.py` | Provider 注册与选择 |
| `roles.py` | 当前 active 数据入口限定 `primary`，历史角色仅保留兼容枚举 |
| `errors.py` | 数据源错误 |

### [`app/services/`](../services/quant-api/app/services/) — 业务服务

| 文件/目录 | 功能 |
|-----------|------|
| `market_data_reader.py` | 查 PG `market_data_files` → DuckDB `read_parquet()` |
| `market_workbench.py` | K 线工作台 coverage/bars 封装 |
| `batch_backtest.py` | watchlist 批量回测 |
| `signal_scanner.py` | 通用信号扫描服务 |
| `review_center.py` | 复盘 note 业务逻辑 |
| **`rqdata_ingest/`** | V1 主数据入库链路 |
| `rqdata_ingest/client.py` | 米筐 API 客户端 |
| `rqdata_ingest/ingestors.py` | 目录/主力/复权/合约/参数等 ingestor |
| `rqdata_ingest/parquet.py` | raw/standard Parquet 写入 |
| `rqdata_ingest/manifest.py` | 入库 manifest 追踪 |
| `rqdata_ingest/quality.py` | 入库质量检查 |
| `rqdata_ingest/bar_sample.py` | 样本 bar 同步 |
| `rqdata_ingest/recovery.py` | 从 raw 回填结构化表 |
| `rqdata_ingest/db.py` | 入库 DB 操作 |

### [`app/signal/`](../services/quant-api/app/signal/) — 信号逻辑

| 文件 | 功能 |
|------|------|
| `scanner.py` | 通用扫描逻辑 |
| `jm_v1b.py` | JM V1-B 专用：日线定方向 + 15m/5m 入场 |

### [`app/strategy/`](../services/quant-api/app/strategy/)

| 文件 | 功能 |
|------|------|
| `su_bing_ema21.py` | API 内嵌苏冰 EMA21 策略（legacy engine 用） |

### [`app/review/`](../services/quant-api/app/review/)

| 文件 | 功能 |
|------|------|
| `backtest_trade.py` | 回测成交 → 复盘 note 映射 |

### [`app/models/`](../services/quant-api/app/models/) — ORM 模型

| 文件 | 主要表 |
|------|--------|
| `data_center.py` | `data_sources`、`exchanges`、`instruments`、`contracts`、`market_data_files`、`data_quality_reports`、主力映射、复权因子、交易参数等 |
| `backtest.py` | `watchlists`、`backtest_tasks`、`backtest_reports`、`backtest_trades`、`backtest_orders`、资金/回撤曲线 |
| `signal.py` | `signal_scan_tasks`、`strategy_signals`、`signal_notifications` |
| `review.py` | `review_notes`、`review_tags`、`review_attachments` |

### [`app/schemas/`](../services/quant-api/app/schemas/) — Pydantic

对应 `models/` 各域的请求/响应 schema：`backtest.py`、`data_center.py`、`market.py`、`signal.py`、`review.py`。

### [`app/db/`](../services/quant-api/app/db/)

| 文件 | 功能 |
|------|------|
| `base.py` | SQLAlchemy Base |
| `session.py` | 会话工厂 |
| `url.py` | 数据库 URL 构造 |

### 异步任务与 CLI

| 文件 | 功能 |
|------|------|
| `queue.py` | Redis 队列 `guiyi-backtests`、`guiyi-signals` |
| `worker.py` | RQ Worker 启动（`python -m app.worker backtests\|signals`） |
| `tasks/backtests.py` | 回测 RQ job 入口 |
| `tasks/signals.py` | 信号 RQ job 入口 |
| `cli.py` | 离线 CLI：数据导入、bar 检查、本地回测 |
| `core/env.py` | 环境变量读取 |

### WebSocket

| 文件 | 路径 | 功能 |
|------|------|------|
| `websocket/backtests.py` | `WS /ws/backtests/{task_no}` | 回测进度推送 |
| `websocket/signals.py` | `WS /ws/signals` | 信号事件推送 |

### [`alembic/versions/`](../services/quant-api/alembic/versions/) — 数据库迁移（10 版）

| 迁移文件 | 内容 |
|----------|------|
| `20260623_0001_data_center_v0.py` | 数据中心基础表 |
| `20260624_0002_batch_backtest_v0.py` | 批量回测/watchlist |
| `20260624_0003_signal_scanner_v0.py` | 信号扫描表 |
| `20260624_0004_review_center_v0.py` | 复盘中心表 |
| `20260624_0005_rqdata_structured_ingest.py` | RQData 结构化入库表 |
| `20260625_0006_market_data_file_symbol_unique.py` | market_data_files 唯一约束 |
| `20260625_0007_rqdata_contract_universe.py` | 合约 universe |
| `20260626_0008_vnpy_backtest_metadata.py` | vn.py 回测元数据 |
| `20260626_0009_market_data_file_data_role.py` | `data_role` 字段 |
| `20260627_0010_backtest_result_detail_tables.py` | 交易明细/曲线表 |

### [`tests/`](../services/quant-api/tests/) — pytest（最近记录 183 passed）

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_health.py` | 健康检查 |
| `test_data_center_api.py` | 数据中心 API |
| `test_market_data_api.py` / `test_market_data_reader.py` | 行情 API 与 DuckDB 读取 |
| `test_data_sources.py` | 数据源抽象与 data_role |
| `test_backtest_task_api.py` | vn.py 回测任务 REST |
| `test_backtest_service_runner.py` | BacktestTaskRunner 与报告持久化 |
| `test_backtest_contract_resolver.py` | 合约解析与交易参数 |
| `test_backtest_vnpy_schema.py` | vn.py 回测 schema |
| `test_equity_curve_generator.py` / `test_drawdown_curve_generator.py` | 资金/回撤曲线生成 |
| `test_vnpy_integration.py` | vn.py 适配层 |
| `test_jm_v1b_daily_direction_fast_entry.py` | JM V1-B 策略 |
| `test_v1b_jm_fixed_backtest_tasks.py` | JM V1-B 固定任务 |
| `test_signal_scanner_api.py` | 信号扫描 API |
| `test_review_center_api.py` | 复盘中心 API |
| `test_rqdata_client.py` / `test_rqdata_structured_ingest.py` / `test_rqdata_sync_common.py` | RQData 客户端、入库、同步公共库 |
| `test_su_bing_ema21_vnpy_draft.py` | 苏冰 EMA21 vn.py 策略草稿 |
| `test_standard_parquet_fixture.py` | 标准 Parquet fixture |
| `conftest.py` | pytest fixtures |

已移除的测试（非 V1 主链路或重复覆盖）：legacy 自研 engine/API、TqSdk 入库、练习者 CSV 导入、实验 demo CLI、样本验收脚本、一次性 backfill 脚本、冗余验收/一致性套件。

---

## 六、[`packages/quant-core/`](../packages/quant-core/) — 共享策略库

| 路径 | 功能 |
|------|------|
| `README.md` | 库说明；规划 indicators/risk/reports 等（尚未落地） |
| `guiyi_quant/strategies/su_bing_ema21/vnpy_strategy.py` | 苏冰 EMA21 vn.py CtaTemplate 草稿 |
| `.../config_schema.py` | 参数 schema |
| `.../default_params.json` | 默认参数 |
| `.../review_tags.json` | 复盘标签建议 |
| `guiyi_quant/strategies/jm_v1b_daily_direction_fast_entry/vnpy_strategy.py` | **V1-B 主策略** |
| `.../config_schema.py` | JM V1-B 参数 schema |
| `.../default_params.json` | JM V1-B 默认参数 |

---

## 七、[`strategies/`](../strategies/) — 策略文档占位

仅含 README，无可执行代码（实际策略在 `packages/quant-core` 和 `services/quant-api/app/strategy`）：

| 目录 | 内容 |
|------|------|
| `su_bing_ema21/README.md` | 苏冰 EMA21 规则说明 |
| `ma_breakout/README.md` | 均线突破系统说明 |
| `n_structure/README.md` | N 字结构策略说明 |

---

## 八、[`data/`](../data/) — 本地数据湖

| 子目录 | 功能 |
|--------|------|
| `raw/rqdata/` | 米筐原始 Parquet 留底 |
| `parquet/canonical/bars/provider=rqdata/` | RQData 标准 canonical Parquet |
| `processed/v1b/` | V1-B 处理后数据 |
| `sample/` | 测试/验收用小样本 |
| `manifests/` | RQData 同步 manifest CSV |
| `reports/` | RQData 数据审计报告 |

当前 active 数据角色：`primary`。历史 `validation` / `legacy_reference` 枚举仅用于兼容旧记录展示，不作为新建回测、信号扫描或行情查询入口。

---

## 九、[`scripts/`](../scripts/) — 运维与数据脚本

**开发环境**：`dev-up.sh`、`dev-down.sh`

**RQData 同步（V1 主链路）**：

- `rqdata_sync_common.py` — 公共 CLI/manifest/品种池
- `rqdata_catalog_sync.py` — 目录、交易日历、交易时段
- `rqdata_contract_universe_sync.py` — 每日上市合约
- `rqdata_main_mapping_sync.py` — 主力/次主力映射
- `rqdata_continuous_contracts_sync.py` — 连续合约映射
- `rqdata_ex_factor_sync.py` — 复权因子
- `rqdata_daily_baseline_sync.py` — 合约日线 baseline
- `rqdata_dominant_daily_baseline_sync.py` — 主力日线 baseline
- `rqdata_trading_params_sync.py` — 手续费/保证金/交易参数
- `rqdata_research_enhancers_sync.py` — 仓单/展期/基差
- `rqdata_market_samples_sync.py` — 跨源校验样本
- `rqdata_recover_raw.py` — 从 raw 回填结构化表
- `rqdata_v1b_jm_asset.py` — V1-B JM 3 年 1d/15m/5m 资产构建

**RQData 审计**：`rqdata_audit.py`、`rqdata_coverage_audit.py`、`rqdata_field_audit.py`

**TqSdk**：当前脚本已移除；后续如 RQData 出现问题，只能以独立任务重新设计 future backup 引入方案。

---

## 十、[`experiments/`](../experiments/) — 隔离实验

### `vnpy_rqdata_demo/`

| 文件 | 功能 |
|------|------|
| `run_demo.py` | CLI：环境检查、fixture 回测、JM smoke、backend E2E |
| `generate_standard_fixture.py` | 合成 60m Parquet fixture |
| `sample_config.json` | 本地样本配置 |
| `p0_009_jm_daily_direction_config.json` | JM 日线方向策略配置 |
| `README.md` | 用法说明 |

### `rqdata_sample_acceptance/`

| 文件 | 功能 |
|------|------|
| `run_sample.py` | 小样本 RQData 下载 → 标准化 → DuckDB → 可选 vn.py smoke |
| `README.md` | 凭据与命令说明 |

---

## 十一、[`docs/`](.) — 文档索引

| 文件 | 功能 |
|------|------|
| `PRD.md` | 产品需求、V1 范围、不做项 |
| `ROADMAP.md` | 阶段路线图 V0/V1/V1.5/V2 |
| `ARCHITECTURE.md` | 系统架构与技术栈 |
| `DATA_CENTER.md` | 数据中心设计 |
| `BACKTEST_ENGINE.md` | 回测引擎设计 |
| `../PROJECT_SNAPSHOT.md` | 新 ChatGPT 项目长期项目快照 |
| `../CURRENT_STATE.md` | 当前仓库状态速览 |
| `PROJECT_INVENTORY.md` | **本文档**：功能与目录说明 |
| `CODEX_HANDOFF.md` | Codex 接手交接 |
| `CODEX_HANDOFF_FOR_CHATGPT.md` | 新 ChatGPT 项目专用交接 |
| `AGENT_WORKFLOW.md` | Cursor/Codex/ChatGPT/WorkBuddy 协作 |
| `AI_DEVELOPMENT_WORKFLOW.md` | ChatGPT + Codex 日常开发模板 |
| `NEXT_STEPS.md` | 下一阶段任务顺序 |
| `STRATEGY_CURRENT_STATE.md` | 当前策略研究状态 |
| `CODE_REVIEW.md` | 外部审查指南 |
| `CLOUDFLARE_WORKSTATION_ACCESS.md` | 本地工作站远程浏览器访问配置 |
| `RQDATA_ONLY_ARCHITECTURE.md` | RQData-only 架构补充 |
| `RQDATA_ONLY_ROADMAP.md` | RQData-only 后续路线 |

---

## 十二、协作与规范目录

### [`tasks/`](../tasks/)

| 文件/目录 | 功能 |
|-----------|------|
| `current.md` | 当前任务与下一阶段顺序 |
| `pending/`、`running/`、`review/`、`done/` | 任务队列目录 |

### [`prompts/`](../prompts/)

| 文件 | 功能 |
|------|------|
| `task-template.md` / `CODEX_TASK_TEMPLATE.md` | 新任务模板 |
| `codex-feature.md` | Codex 功能开发提示 |
| `code-review.md` | ChatGPT 代码审查提示 |
| `workbuddy-bugfix.md` | WorkBuddy UI bug 修复提示 |

### [`.cursor/rules/`](../.cursor/rules/)

| 文件 | 功能 |
|------|------|
| `001-project.mdc` | 项目全局规范 |
| `002-frontend.mdc` | 前端规范 |
| `003-backend.mdc` | 后端规范 |
| `004-quant.mdc` | 量化/回测规范 |
| `005-safety.mdc` | 安全与风控（CRITICAL） |

### [`.agents/skills/`](../.agents/skills/) — 20 个领域技能

回测、数据、策略、前端、后端、复盘、信号、风控、测试、UI 修复、Git 工作流、项目治理等。

### [`.codex/agents/`](../.codex/agents/) — 5 个审查 Agent

`architecture-reviewer`、`backtest-reviewer`、`frontend-reviewer`、`product-reviewer`、`risk-reviewer`。

### [`backtests/`](../backtests/)

`reports/`、`results/` — 本地回测输出目录（正式结果在 PostgreSQL）。

### [`screenshots/`](../screenshots/)

UI 截图存档，供 WorkBuddy 修复参考。

---

## 十三、已知缺口与注意事项

1. **占位页面**：仪表盘、策略管理、系统设置未接后端。
2. **Pinia 未成为主状态层**：核心页用页面内 `ref` 拉数。
3. **两套回测 API**：`backtestApi.ts`（RESTful）与 `strategy.ts`（legacy run-batch）并存。
4. **批量回测**：路由存在但侧栏无菜单入口。
5. **报告口径**：年化收益、手续费/滑点、最大回撤百分比需持续按 [`CURRENT_STATE.md`](../CURRENT_STATE.md) 和 [`ROADMAP.md`](ROADMAP.md) 追踪。
6. **V1 明确不做**：自动实盘、CTP、TqSdk 交易、信号自动下单。
7. **实验目录边界**：RQAlpha / XMA PoC 不入正式报告链路，不能替代 vn.py + PostgreSQL 的可信回测结论。

---

## 十四、可进一步深挖的子目录（第二轮）

如需函数级或流程级说明，建议按以下优先级继续展开：

| 优先级 | 路径 | 建议深挖内容 |
|--------|------|--------------|
| P0 | `app/services/rqdata_ingest/ingestors.py` | 各 Ingestor 类、入库顺序、PG 表映射 |
| P0 | `app/vnpy_integration/result_converter.py` | vn.py raw → 归一报告字段映射 |
| P0 | `packages/quant-core/.../jm_v1b_daily_direction_fast_entry/vnpy_strategy.py` | 入场/出场/止损/持有 bar 逻辑 |
| P1 | `app/services/market_data_reader.py` | DuckDB SQL 构造、多周期/auxiliary bar |
| P1 | `app/signal/jm_v1b.py` | 扫描条件、daily_direction_blocked 原因 |
| P1 | `app/backtest/service.py` | 任务生命周期、持久化写入顺序 |
| P2 | `scripts/rqdata_v1b_jm_asset.py` | JM 3 年资产构建 CLI 参数与步骤 |
| P2 | `apps/quant-web/src/pages/market/index.vue` | K 线 marker 与 query 深链逻辑 |

---

## 十五、快速验证命令

```bash
./scripts/dev-up.sh
uv run --project services/quant-api pytest -q
cd apps/quant-web && pnpm build
```

Web 入口：`http://127.0.0.1:5173`（前端） / `http://127.0.0.1:8000/docs`（API 文档）
