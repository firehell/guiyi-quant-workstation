# BACKTEST_ENGINE.md

更新时间：2026-07-19

## 1. 定位

V1 使用 vn.py / VeighNa CTA BacktestingEngine。归一量化负责数据 Gate、任务编排、参数校验、结果转换、报告入库、Web 展示和可信审计。

回测不等于实盘，不生成自动交易指令。

## 2. 数据入口

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_policy = "passed_only"
quality_status = "passed"
```

公开 `/api/backtests/tasks`、inline `/run`、`/run-batch` 和 fixed JM 均属于 formal consumer。客户端只提交行情 identity 和可选 `profile_id`，不得提交主/辅助本地路径、data role、quality、data version 或 warning override。服务端通过 `ProfileLineageResolver` 固定 active Profile binding；主资产与辅助资产必须属于同一 Profile。

低层 `GuiyiBacktestRequest` 仍可接收路径，但仅供显式 `research_only` 的 legacy、experiment 和 test fixture 使用，不能通过公开 formal API 持久化为正式任务或报告。

Formal contract 错误采用稳定 code：`BACKTEST_FORMAL_PATH_FORBIDDEN`、`BACKTEST_PROFILE_NOT_FOUND`、`BACKTEST_PROFILE_BINDING_MISSING`、`BACKTEST_PROFILE_MARKET_FILE_MISSING`、`BACKTEST_PROFILE_QUALITY_BLOCKED`、`BACKTEST_PROFILE_RANGE_NOT_COVERED`、`BACKTEST_PROFILE_FILE_MISSING`、`BACKTEST_PROFILE_IDENTITY_MISMATCH`、`BACKTEST_PROFILE_BINDING_CHANGED`。错误 context 不返回物理文件路径；并发 binding 切换使用 HTTP 409，其余契约拒绝使用 HTTP 422。

禁止 validation、legacy_reference、candidate、failed、live DB、旧 TqSdk / 天勤和交易练习者数据进入正式回测。

## 3. 调用链

```text
Backtest API
-> BacktestService
-> ProfileLineageResolver (active / passed_only)
-> immutable binding snapshot
-> vn.py runner
-> ResultConverter
-> BacktestReport / Trade / Order
-> derived equity / drawdown / trusted metrics
-> trust audit CLI
```

- report 曲线从 closed trades 派生，忽略外部输入的 equity/drawdown 曲线。
- task 保存 `profile_id`、主 `market_data_file_id` 和包含全部辅助资产的 immutable snapshot；report 深拷贝 task snapshot，不按当前 binding 重新解析。
- snapshot 记录 `resolver_name=ProfileLineageResolver`、`resolver_contract_version=backtest_profile_v1` 和 `quality_policy=passed_only`。
- formal 任务另附 `indicator_policy_snapshot`（`strategy_indicator_policy_v1`）：创建时 fail-closed；旧报告无 snapshot 时 API 返回 `indicator_policy_status=legacy_policy_unavailable`，禁止用当前 Registry 猜测。
- formal policy 必须允许 `formal_backtest` consumer；精确的 JM V1-B v1b.0 冻结链路使用独立 `frozen_legacy_backtest` consumer，其他策略不得伪造 legacy 身份。
- batch task 可因多资产令顶层 `market_data_file_id` 为空，但 snapshot 必须列出全部资产，且每个 report 的文件 ID 必须非空。
- runner 只执行 snapshot 固定的文件 ID/路径，并要求 Parquet 显式携带 `data_role=primary`、`quality_status=passed`；缺字段不再默认通过。
- trade/order 保存 signal/fill/order 映射与 lineage summary。
- 当前 bar 信号采用 `next_bar_open` 成交，禁止当前 bar 提前成交。
- 手续费、滑点、乘数、price tick、保证金和真实合约映射必须可追溯。

## 4. Stage 13-G 结论

可信基线：

- report：`report_id=14`
- task：`BTV-20260709134008-0a42eca8`
- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- data：`local_parquet / primary / passed`
- trades：155，全部 `lineage_status=mapped`
- orders：239，全部 `mapping_status=mapped`
- trust audit：10/10 checks `passed`
- total return：`-0.1928553100985149`

`passed` 只代表数据、执行、成本、trade/order/equity/metrics 和敏感输出一致，不代表策略盈利、稳定或可实盘。

该结论本身不证明策略盈利、稳定或实盘准入。消费者数据准入已由 C2-05 取得 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`；`DATA_LAYER_REAUDIT_REQUIRED` 仍只保留给全历史 residual 治理，不改变 report 14 的冻结边界。

只读命令：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

## 5. 必查风险

- 未来函数和数据泄露。
- 分型/突破/方向信号是否等待确认 bar。
- 成交是否严格晚于 signal time。
- 手续费、滑点、乘数、保证金和 rollover 成本。
- 最大回撤、最大连续亏损、期望值和资金占用。
- 单笔交易能否回到 K 线和 review note。
- 样本内与样本外是否分离。

Stage 13 审计不重跑策略，不能单独证明没有未来函数或过拟合。XMA PoC 已明确存在重绘风险，不得进入正式回测或信号。

## 6. 下一步

- `20260718_0024` 仅新增 task/report nullable JSON snapshot，无 UPDATE、server default 或历史 backfill。包含 report 14 的隔离 PostgreSQL 已完成 `0023 -> head -> 0023 -> head` roundtrip，canonical PostgreSQL 已应用；report 14、trades、orders 和 trust audit 与迁移前副本一致，历史 snapshot 保持 null。
- 保持 `report_id=14` 作为回归基线，不修改策略参数以改善收益。
- 阶段 4 已取得 `INDICATOR_CONTRACT_READY / HTDY_STRICT_FORMAL_REPORT_READY`；X5-02 已生成只读 full-window dry-run 与 `HTDY_TRUSTED_REPORT_APPLY_PACKET_READY` 审批包，但没有创建正式报告或执行独立 OOS/walk-forward。后续写入必须使用独立 TASK、显式 canonical PostgreSQL 写入批准，并在创建新 report 后立即运行 trust audit。
- D4-00 HTDY original 审计最终 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；original 不得进入正式回测，独立 causal strict 仅获得历史正式报告输入资格。
- OOS / walk-forward 默认仅输出文件或隔离数据库；任何 canonical PostgreSQL 写入都需独立审批包和用户明确批准。trust audit passed 不能直接写为策略有效，最终候选结论必须留给阶段验收任务。
- X5-04 的 HTDY 专用 runner 已代码完成：只运行 `oos_fixed`，用 72 根 passed-only 15m bar 进行 indicator-only 预热，并在 OOS 起点创建全新策略状态。正式入口必须先验证 hash-bound 的 X5-03 `HTDY_TRUSTED_BACKTEST_CANDIDATE` 包以及 candidate/report14 双 audit；缺失时在打开 DB session 前 exit 2，不生成 OOS 结果。当前因此仍为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`。
- X5-04 独立 binding snapshot 必须与 X5-03 candidate 的 Profile、binding、file ID、data version 和 snapshot hash 全等；不恢复 validation protocol 中已 superseded 的旧数据文件。协议继续冻结策略、参数、指标、窗口、执行时点、成本和 hard-reject 阈值。
- X5-04 正式 `oos_fixed` 已输出 `OOS_HARD_REJECT_TRIGGERED`：179 trades，`max_consecutive_losses=12`、`profit_factor=0.16355909337101607`，并保留末尾 sample-end forced exit 同时刻 signal/fill 的结构审计失败。packet 不得覆盖，后续仅允许 diagnostic-only X5-05，不能翻转该 Gate。
- X5-05 专用 diagnostic-only runner 将 frozen A/B/C 作为无拟合、无选参的 `rolling_oos_stability`，逐 fold 记录 72-bar warmup、binding/config/cost/result/audit hash；81 组 commission/slippage/gap/margin post-trade overlay 不重新撮合、不修改 frozen parameter hash。所有亏损、空交易和失败 fold 必须保留。
- X5-05 已从 source commit `7b94867e5bd8779bab4914447d1dbedea92a1d7a` 正式执行并输出 `DIAGNOSTIC_CONFIRMS_REJECTION`。A/B/C 均通过结构审计并分别保留 84/101/166 笔交易，但都因最大连续亏损和 profit factor 独立复现 frozen numeric reject；packet hash 为 `1d0fe23c2b275ede0d5c96e5ffa477fd1008571cb0087dd7fb845b80b8c8e8c7`。该诊断不翻转 X5-04 hard reject。
- X5-06B 新增独立 validation-context API：只读固定、hash-valid 的 X5-03/04/05 evidence，严格对账 report 15 identity、Profile binding 和 frozen hashes；派生 OOS/WF/reject 字段不写回 report summary。Review 页面只展示该上下文，策略与交易事实仍来自原始 report/trade；正式 Gate 需一个真实 ReviewNote、exact bars 和 browser round-trip 全部通过。
- X5-03 使用专用 repeatable-read 单事务应用器：固定 X5-02 packet hash 派生 task_no，写入/flush 后在 commit 前运行 candidate 与 report14 双 trust audit、精确 row delta、facts hash、formal lineage 和 future/fill timing。任一失败整体 rollback 并在新会话验证零新增；重复 apply fail-closed。正式执行已创建 task `23` / report `15` / trades `1255` / orders `2510`，双 audit passed 且 report14 未变。schema 不新增 equity/metrics 表，equity 由 stored trades 确定性复算，metrics 位于 report summary。
- 旧报告不自动回填 lineage；如需修复必须另开只读审计与受控 backfill Gate。
- `research_only` 字段语义拆分需先设计兼容 schema/API，本轮不重命名历史字段。
