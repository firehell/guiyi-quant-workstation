# 归一量化项目事实源

更新时间：2026-07-15

## 定位

归一量化是本地运行、单用户使用的国内期货量化研究工作站。当前重点是 V1 / V1-B 的可信研究闭环：

```text
数据更新 -> 数据质量检查 -> 标准化存储 -> K 线查看 -> 策略 / 信号
-> 回测 -> 报告 -> 单笔复盘 -> 人工观察 -> 前向验证
```

项目不是 SaaS，不是无人值守自动交易机器人，不连接实盘账户自动下单，不把预警或回测结论写成交易指令。

## 当前主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

active 数据入口硬约束：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、回测和 Stage 9 前置 Gate 默认使用 `quality_status=passed`。`validation`、`legacy_reference`、`candidate`、旧 TqSdk / 天勤和交易练习者数据不得进入默认 active 链路。

## 当前总体状态

当前数据层状态是：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不等同于数据层最终封板完成。当前 Phase 3 口径仍保留 `metadata_gap=1853`、pre-2020 周线缺口和 actual contract 缺口。

## Canonical 文件职责

| 文件 | 职责 |
|---|---|
| `PROJECT_SOURCE.md` | 长期目标、系统边界、主链路、不可突破范围 |
| `STATUS.md` | 当前阶段、已实现能力、未完成 Gate、阻塞项 |
| `DECISIONS.md` | 已确认架构/数据/回测/运行/协作决策 |
| `CODEX_TASKS.md` | 当前任务池、优先级、后续执行顺序 |
| `TESTING.md` | 常用验证命令、文档检查和 Gate 命令 |
| `docs/DATA_CENTER.md` | 数据层 deep canonical |
| `docs/ARCHITECTURE.md` | 系统架构 deep canonical |
| `docs/BACKTEST_ENGINE.md` | 回测口径 deep canonical |
| `docs/SIGNAL_EVENTS.md` | 信号事件和企业微信边界 deep canonical |
| `docs/CODEX_HANDOFF.md` | Codex 接手事实和最小验证 |
| `docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md` | GitHub Native V3 控制平面权威模型 |
| `docs/decisions/ADR-WS-001-github-native-control-plane.md` | GitHub Native 控制平面架构决策记录 |
| `docs/gpt/project_sources/` | GPT GitHub 读取导航与兼容摘要包，不反向成为事实源 |
| `docs/gpt/GITHUB_READ_ORDER.md` | GPT 已授权读取 GitHub 后的默认读取顺序 |

## AI 工作站控制平面

当前工作站控制平面进入 V3 GitHub Native 模型：

```text
GitHub main canonical docs
-> task branch TASK
-> GitHub Issue lifecycle
-> Draft PR / PR delivery
-> local .ai/results evidence
```

关键边界：

- Issue 不取代 TASK；`docs/tasks/<TASK_ID>.md` 仍是 dispatcher 和 Codex 的执行契约。
- GPT 默认只在任务分支写文档、设计和 TASK 契约，不直接写 `main`。
- Draft PR 是任务从设计到交付的共享容器，不代表自动 merge。
- `.ai/results/<TASK_ID>/` 保持 local-first，只同步脱敏摘要。
- WorkBuddy 是远程 PM/QA；CodeBuddy 是本地执行控制器；Codex 是唯一编码执行器。
- 用户保留 Plan、生产写入、merge 和 deploy 的最终批准权。

## 不做事项

- 不自动交易，不自动生成或发送订单。
- 不把企业微信提醒写成买卖指令。
- 不把单次 smoke 写成长稳 Gate。
- 不把 `trust audit passed` 写成策略盈利、稳定或可实盘。
- 不把数据文件存在写成数据最终可信。
- 不把 historical replay smoke 写成 live-confirmed smoke。
- 不把 `.env`、webhook、token、password、cookie、license 或账号凭据写入仓库。

## 推荐 GPT 入口

浏览器 GPT 优先读取：

1. `docs/gpt/project_sources/00-INDEX.md`
2. `PROJECT_SOURCE.md`
3. `STATUS.md`
4. `DECISIONS.md`
5. `CODEX_TASKS.md`
6. `docs/gpt/PROJECT_SOURCE_MANIFEST.md`
7. `docs/gpt/GITHUB_READ_ORDER.md`
8. 任务相关 deep canonical，例如 `docs/DATA_CENTER.md`、`docs/ARCHITECTURE.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md` 或 `docs/workstation/`

`docs/gpt/project_sources/*.md` 只作为兼容摘要；若与 canonical 文件冲突，以 canonical 文件为准。截图、外部 PDF、未提交本地文件和 `.ai/results` 原始 evidence 仍需按任务单独提供。
