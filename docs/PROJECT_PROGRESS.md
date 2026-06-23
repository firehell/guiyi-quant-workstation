# 归一量化项目进度

> 更新日期：2026-06-23
> 当前阶段：Phase 1 数据中心 V0 准备期
> 当前状态：脚手架可运行 + 文档体系较完整 + 业务闭环待实现

## 1. 总体状态

| 模块 | 状态 | 说明 |
|---|---|---|
| 项目定位 | 已明确 | 本地国内期货量化研究、回测、复盘、信号扫描、模拟交易和后期半自动实盘辅助系统 |
| 第一阶段边界 | 已明确 | V0 命令行原型 + V1 Web 研究闭环，不做全自动实盘 |
| 全局总控文档 | 已建立 | `docs/归一量化_Codex从零搭建总控文档_V1.md` |
| 项目大纲 | 已同步 | `docs/PROJECT_BOOK.md` 已按新版总控重写 |
| 技术栈 | 已明确 | FastAPI + PostgreSQL/Parquet/DuckDB + Vue 3/Vite/TypeScript |
| 项目骨架 | 已创建 | docs、services、apps、strategies、packages、tasks 等目录已存在 |
| Agent 协作规则 | 已创建 | AGENTS.md、CLAUDE.md、prompts、skills 已存在 |
| TqSdk 源码参考 | 已加入本地 | `tqsdk-python/` 作为源码参考目录，不作为项目代码提交 |
| 数据仓方案 | 已明确 | PostgreSQL 管元数据，Parquet 管行情大文件，DuckDB 做本地研究查询 |
| 后端 API | 初始骨架 | FastAPI 最小服务已有健康检查和 mock dashboard summary |
| 前端工作台 | 初始骨架 | Vue 3/Vite/TypeScript/Naive UI 页面与组件已存在 |
| 策略目录 | 初始骨架 | 已有 su_bing_ema21、ma_breakout、n_structure README |
| 回测引擎 | 待实现 | 需要逐 bar 回放、交易成本、保证金、绩效模块 |
| 信号扫描 | 待实现 | 需要多品种多周期扫描和信号解释 |
| 单笔复盘 | 待实现 | 需要复盘记录、标签、执行偏差和归因 |
| 模拟交易 | 后续扩展 | V1.5 做模拟和人工确认，V1 不做全自动实盘 |

## 2. 已完成

- 建立归一量化本地工作站目录结构。
- 建立项目协作规则和开发边界。
- 明确第一阶段只做 V0 / V1，不做全自动实盘。
- 明确阶段口径：
  - V0：命令行验证数据、Parquet、DuckDB、策略、回测 JSON。
  - V1：Web 研究闭环，K线、策略、回测、报告、信号、复盘。
  - V1.5：模拟账户、企业微信提醒、人工确认。
  - V2：小资金半自动实盘辅助，风控拦截。
  - V3：AI 总结、归因、策略迭代辅助。
- 建立基础文档：
  - `docs/归一量化_Codex从零搭建总控文档_V1.md`
  - `docs/PROJECT_BOOK.md`
  - `docs/PRD.md`
  - `docs/ARCHITECTURE.md`
  - `docs/DATA_CENTER.md`
  - `docs/ROADMAP.md`
  - `docs/RISK_CONTROL.md`
  - `docs/BACKTEST_ENGINE.md`
  - `docs/AGENT_WORKFLOW.md`
- 建立前端页面骨架：
  - Dashboard
  - 数据中心
  - 行情
  - 策略
  - 回测
  - 信号
  - 复盘
  - 设置
- 建立前端基础能力：
  - Vue Router。
  - Pinia store。
  - Axios API client。
  - sample K线组件。
  - ECharts 包装组件。
  - WebSocket client。
- 建立后端基础能力：
  - FastAPI app。
  - CORS 配置。
  - `/health` 和 `/api/health`。
  - `/api/dashboard/summary` mock 接口。
  - pytest 健康检查测试。
  - Alembic 初始化。
- 建立初始策略目录：
  - 苏冰 EMA21。
  - 均线突破。
  - N 字结构。

## 2.1 第一阶段基础运行验收

当前基础依赖和前后端采用分开启动：

```bash
# 基础依赖
docker compose up -d

# 后端 API
cd services/quant-api
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 前端工作台
cd apps/quant-web
pnpm dev --host 127.0.0.1 --port 5173
```

验收清单：

| 检查项 | 命令或地址 | 期望结果 |
|---|---|---|
| 前端可打开 | `http://127.0.0.1:5173` | 返回 Vite 前端页面 |
| 后端健康检查 | `curl http://127.0.0.1:8000/api/health` | 返回 `status: ok` |
| PostgreSQL 连通 | `docker exec guiyi-postgres pg_isready -U guiyi -d guiyi_quant` | `accepting connections` |
| Redis 连通 | `docker exec guiyi-redis redis-cli ping` | `PONG` |

说明：第一阶段暂不把前端和后端加入 Docker Compose；Compose 只负责 PostgreSQL / Redis 基础依赖。

## 3. 当前正在推进

### Phase 1：数据中心 V0

目标：先用 sample/mock 数据跑通标准数据仓、文件规范、质量检查和 API，再接入 TqSdk/RQData/Tushare 等真实数据源适配器。

当前待办：

- 设计统一 `DataSource` 接口。
- 实现 sample/mock K 线导入链路。
- 实现 `TqSdkDataSource` 最小行情下载能力。
- 预留 RQData / Tushare / AKShare 补充适配器。
- 设计合约元数据表。
- 设计 K 线数据 Parquet 分区规范。
- 设计数据下载任务表。
- 设计数据质量报告结构。
- 用 DuckDB 查询落地后的 Parquet。
- 在 Web 数据中心展示数据源、任务状态和质量结果。

## 4. 近期优先级

| 优先级 | 任务 | 产出 |
|---|---|---|
| P0 | 数据源配置规范 | `.env.local` 本地配置、`.env.example` 模板、数据源枚举 |
| P0 | 标准 K 线 schema | 统一 OHLCV、成交额、持仓量、provider 字段 |
| P0 | DataSource 接口 | TqSdk/RQData/Tushare 适配器统一契约 |
| P0 | Parquet 落地 | 按交易所、品种、合约、周期、年份或月份分区 |
| P1 | PostgreSQL 元数据 | 合约、数据任务、数据质量报告 |
| P1 | DuckDB 查询验证 | 能从本地 Parquet 读取回测输入 |
| P1 | 数据中心页面 | 展示数据源、下载任务、覆盖情况和质量状态 |
| P2 | TqSdk 源码参考整理 | 明确可用 API、限制和凭证读取方式 |

## 5. 风险与约束

| 风险 | 当前判断 | 应对 |
|---|---|---|
| 外部数据源字段差异 | 会影响统一入库和回测一致性 | 建立标准字段、合约映射、provider 标识和质量报告 |
| TqSdk 凭证泄露 | 账号、密码、授权信息敏感 | 只读环境变量，不写入代码库或文档正文 |
| 本地参考源码误提交 | `tqsdk-python/` 体积大且不是项目源码 | 加入 `.gitignore`，只作为本地查阅资料 |
| 回测过度乐观 | 容易误判策略有效性 | 默认纳入手续费、滑点、保证金、成交合理性检查 |
| 策略过拟合 | 初期策略数量少、样本有限 | 保留样本外验证、参数约束和策略版本记录 |
| 过早做实盘 | 风险过大 | 第一阶段只做研究、复盘、信号、模拟和人工确认 |

## 6. 下一轮开发建议

1. 新建后端数据源适配模块，定义统一接口。
2. 建立标准 K 线 schema 和 Parquet 分区目录。
3. 实现 sample/mock K 线落地到 Parquet。
4. 增加 DuckDB 查询样例和数据质量检查命令。
5. 建立合约、数据任务、质量报告的 SQLAlchemy 模型和 Alembic migration。
6. 实现 TqSdk 行情下载最小闭环，凭证只读 `TQSDK_USERNAME` / `TQSDK_PASSWORD`。
7. 将数据中心页面从静态页面接到真实 API。

## 7. 当前不做

- 不做全自动实盘。
- 不做云端部署。
- 不做多用户权限。
- 不做 tick 级高频回测。
- 不做复杂组合管理。
- 不做与当前数据中心 V0 无关的大范围重构。
