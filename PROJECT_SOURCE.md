# 归一量化项目事实源

更新时间：2026-07-20

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

当前数据层状态已从旧 Phase 3 固定缺口口径切换为“formal consumer 准入”与“全历史维护 backlog”并列的口径：

```text
V1_DATA_CONTRACT_FROZEN
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
```

`V1_DATA_CONTRACT_FROZEN` 表示全历史 expected window、周线完成语义、actual rank=1 范围、派生周期、五层状态和消费者准入边界已经冻结为文档与纯代码契约。

`CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是严格 formal consumer Gate：C2-05 已以 direct PostgreSQL read-only snapshot、真实 Parquet、49 条消费者矩阵和 13 个 hard gate 复跑通过。它只允许 Market、Backtest、Signal 与 Review 在既有 Profile/lineage 契约内使用数据；不代表所有历史 residual 清零，也不授权 live runtime、OOS 结论、企业微信 autosend 或自动交易。

`DATA_LAYER_REAUDIT_REQUIRED` 是 provider-earliest、TradingCalendar、TradingSession、physical partial 与 warning/failed 资产的独立全历史维护 backlog。它不否定 formal consumer Gate，但也不得被 Ready 标记覆盖或降级。

`FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只说明仓库中的 full-history manifest 示例和大量 `rqdata_*_v2_history_*` / actual-contract manifest 强烈支持“物理历史数据已经大规模下载”的判断；它不代表本地全部 Parquet、direct PostgreSQL、quality、Profile binding 或 formal consumer contract 已验收。

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不等同于数据层最终封板完成。`data/reports/data_layer_final_audit_phase3_20260712/` 中的 `metadata_gap=1853`、`pre_2020_weekly_missing=34` 和 actual contract gap 旧固定数字保留为历史审计模型快照，不再作为当前确定下载缺口或批量修复清单。

当前暂停所有基于旧 `1853 / 34 / 45` 数字的批量修复。相关段落中的 Audit V2、Profile rollout 与 formal consumer Gate 均是历史阶段记录，不再属于当前任务池。

阶段 4/5 已按冻结契约完成工程闭环：阶段 4 为 `STAGE4_COMPLETED / INDICATOR_CONTRACT_READY`；阶段 5 为 `STAGE5_COMPLETED / STRATEGY_EVALUATION_PIPELINE_READY`。HTDY 的研究结论为 `REJECTED_RESEARCH_CANDIDATE`：X5-04 numeric hard reject 与 rolling numeric rejection 均保持，Review、数据等价、sample-end accounting liquidation 和 blocked/rejected decision semantics 已闭合。候选被淘汰是合法研究终态，不是工程失败，也不授权调参或自动重跑。

当前下一业务阶段固定为阶段 6 JM T3 / T4 真实 Gate；它仍需新稳定 runtime 副本、独立 Plan、hash-bound approval 与每次真实写入授权。阶段 4/5 完成不等于 live、通知、长稳或自动交易 Ready。

本轮工具执行顺序固定为完整 Cursor Wave → 单次交接 → Codex Wave，两种工具不在任务间来回穿插。D4-00（`HTDY-SOURCE-XMA-AUDIT-400`）审计证据已落盘且不再重开公式审计；最终 Gate 诚实为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不得宣称 `HTDY_XMA_SEMANTICS_AUDITED`、OOS、live 或长稳 Ready。

阶段 A 当前 Gate：

```text
V1_DATA_CONTRACT_FROZEN
CANONICAL_OLD_AUDIT_MARKED_HISTORICAL
WORKSTATION_NON_BLOCKING_SUPPORT_MODE
CURSOR_CANONICAL_SYNC_PREPARED
```

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

当前工作站控制平面进入 V3 GitHub Native + WorkBuddy Unified V3 模型：

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
- WorkBuddy 是上班/远程统一协调入口，负责 PM、最少必要专家、QA、视觉验收、文件/文档处理和交付摘要；WorkBuddy 对话与 memory 不是状态源。
- `scripts/ai/workbuddy_task.sh` 是 WorkBuddy 唯一白名单 facade，只调用既有受控脚本，不接受自由 shell，不裸调 Codex，不维护第二状态。
- CodeBuddy 是 compatibility-only 执行入口，Demo 通过后 deprecated；旧任务仍可读取和回退。
- Codex 是核心和复杂开发 writer；writer lock 仍使用 `codex`，不新增 `workbuddy` writer。
- Copilot 仅适用于明确 R3/L1、单模块、最多 5 文件的小修改；否则升级给 Codex。
- 居家 L1 可直接调用 dispatcher，不强制经过 WorkBuddy。
- 用户保留 Plan、生产写入、merge 和 deploy 的最终批准权。

当前迁移状态：

```text
WORKBUDDY_V3_CONTROL_PLANE_FIX_MERGED
WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING
WORKSTATION_NON_BLOCKING_SUPPORT_MODE
```

控制面 P0/P1 修复已合并到 `main`，不再作为 V1 数据重审业务启动前置阻塞。WorkBuddy Demo、旧 Issue / PR 人工清理和文档迁移仍可继续，但属于非阻塞支持轨，不得阻塞全历史盘点或 Audit V2。

工作站后续只修复真实业务 Task 可复现暴露的问题；每个缺陷独立建 follow-up，不在业务 Task 中顺手扩展控制面。当前不继续扩展多项目、复杂模型路由、自动 merge/deploy、Dashboard 或代理团队模拟。该状态不表示 WorkBuddy FROZEN，也不改变数据、Profile、消费者或真实运行 Gate。

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
