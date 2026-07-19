# 火天大有（HTDY）指标说明

## Web 观察层（已交付）

主图指标 ID：`huo_tian_da_you`（见 `apps/quant-web/src/utils/mainIndicators.ts`）

实现位置：

- 计算：`apps/quant-web/src/utils/indicators.ts`（`calculateHuoTianDaYou` / XMA 通道）
- 渲染：`apps/quant-web/src/components/kline/KlineChart.vue`
- 交互：`apps/quant-web/src/pages/market/chart.vue`

UI 约束：

- 标签：`观察专用 · 会重绘`
- 不接入正式 marker、信号扫描、回测或企业微信

## 风险审查

必读：[`docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`](../tdx_xma_bands/INDICATOR_RISK_REVIEW.md)

## 公式规范（已补齐）

用户已授权将完整通达信公式写入 tracked docs。当前三份规范文件：

- [`INDICATOR_SPEC.md`](INDICATOR_SPEC.md)：原始公式、变量表和公式拆解。
- [`INDICATOR_RISK_REVIEW.md`](INDICATOR_RISK_REVIEW.md)：未来函数、重绘和接入边界审查。
- [`STRATEGY_SPEC.md`](STRATEGY_SPEC.md)：`huotian_dayou_original_v0` observation-only 策略骨架。

结论保持不变：原始公式含 `XMA(XMA(...))`，只能 observation-only。

## 原始 Observation-Only PoC（已补齐）

PoC 位置：

- [`../../../experiments/htdy_indicator/htdy_original_core.py`](../../../experiments/htdy_indicator/htdy_original_core.py)：完整原始公式数值复刻。
- [`../../../experiments/htdy_indicator/export_htdy_original.py`](../../../experiments/htdy_indicator/export_htdy_original.py)：CSV / JSON 导出 CLI。
- [`../../../experiments/htdy_indicator/README.md`](../../../experiments/htdy_indicator/README.md)：运行方式和风险边界。

PoC 输出 `ZK1/ZD1/ZD2/黄K/白K/买多信号/卖空信号/VAR23/回调买/XG/DDX/V2/V5/V10/V20/DY/DY2/XG2`，并记录：

- `status=observation_only`
- `repainting_risk=known`
- `CAPITAL=0` 期货分支
- `FROMOPEN=1.0` PoC 默认值
- `CURRBARSCOUNT` 的 PoC 图表末端语义

本 PoC 只作为后续 Web 对齐和 Golden Sample 的数值基准，不接入正式策略、回测、扫描、live、数据库、报告或通知链路。

## Strict Backward-Looking V1（第 3 步）

第 3 步新增 `huotian_dayou_strict_v1` 研究候选：

- [`STRICT_V1_SPEC.md`](STRICT_V1_SPEC.md)：strict v1 改写方案、字段边界和 Gate。
- [`../../../experiments/htdy_indicator/htdy_strict_core.py`](../../../experiments/htdy_indicator/htdy_strict_core.py)：纯函数实验实现。
- [`../../../services/quant-api/tests/test_htdy_strict_core.py`](../../../services/quant-api/tests/test_htdy_strict_core.py)：future-tail / append consistency / warm-up 测试。

strict v1 使用 `double_trailing_ema` 替代原始双层 `XMA`，只证明当前研究候选不读取未来 bar。它仍是 `strict_research_candidate`，不接入正式策略、回测报告、扫描、live、数据库或企业微信。

## Golden Sample（第 4 步）

- [`GOLDEN_SAMPLE_ACCEPTANCE.md`](GOLDEN_SAMPLE_ACCEPTANCE.md)：固定 JM 256 根样本、自动数值结果、页面检查和外部 oracle Gate。
- [`../../../experiments/htdy_indicator/golden_sample_manifest.json`](../../../experiments/htdy_indicator/golden_sample_manifest.json)：tracked lineage、checksum 和输出摘要。
- [`../../../services/quant-api/tests/test_htdy_golden_sample.py`](../../../services/quant-api/tests/test_htdy_golden_sample.py)：真实固定样本与错误 lineage/checksum 回归。

当前状态是 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`。用户已提供 `JM8 焦煤主连 15分钟` 通达信截图，覆盖固定样本窗口并通过人工视觉核对；未提供通达信数值导出，因此不声明逐点数值 oracle pass。

## Offline Candidate Eval（第 5 步）

- [`OFFLINE_CANDIDATE_EVAL.md`](OFFLINE_CANDIDATE_EVAL.md)：`huotian_dayou_strict_v1` 离线候选评估边界、版本命名和 runner 用法。
- [`../../../experiments/htdy_indicator/offline_candidate_eval.py`](../../../experiments/htdy_indicator/offline_candidate_eval.py)：只读离线候选事件 runner。
- [`../../../services/quant-api/tests/test_htdy_offline_candidate_eval.py`](../../../services/quant-api/tests/test_htdy_offline_candidate_eval.py)：版本、能力边界、数据 lineage、短窗口和输出测试。

当前只允许写成 `huotian_dayou_strict_v1 offline backtest candidate evaluated`。第 5 步不创建正式 backtest task，不写报告，不写 `strategy_signals` / `signal_events`，不接 scanner、live evaluator、数据库或企业微信。

## Formal Backtest Candidate（候选实现）

- [`FORMAL_BACKTEST_CANDIDATE_PLAN.md`](FORMAL_BACKTEST_CANDIDATE_PLAN.md)：正式可信回测候选边界、策略版本、撮合口径、成本口径、Report Gate 和 GPT 外部复核标准。
- [`../../../packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/`](../../../packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/)：`huotian_dayou_strict / v0.1.0-backtest-candidate` 策略候选实现。
- [`../../../experiments/htdy_indicator/formal_backtest_candidate.py`](../../../experiments/htdy_indicator/formal_backtest_candidate.py)：只读 dry-run helper，输出 normalized `trades / orders / strategy_execution_events / summary`。
- [`../../../services/quant-api/tests/test_htdy_formal_backtest_candidate.py`](../../../services/quant-api/tests/test_htdy_formal_backtest_candidate.py)：策略规则、成本 Gate、next-bar fill、冲突/反手/止损优先、dry-run lineage 和 trust audit 消费回归。

X4-06 已证明 `huotian_dayou_strict / v0.1.0-backtest-candidate` 可经 `ProfileLineageResolver / passed_only` 进入 formal historical backtest/report 输入，Gate 为 `HTDY_STRICT_FORMAL_REPORT_READY`。本任务未创建真实 `BacktestReport`，不写 `strategy_signals` / `signal_events`，不接 scanner、live evaluator、数据库 migration 或企业微信。后续写报告必须新建独立 task / report，并在写入后立即运行 trust audit；`report_id=14` 继续冻结为历史可信基线。

## X5-02 Trusted Report Apply Packet

X5-02 使用当前正式 Profile active binding 生成独立 immutable execution snapshot，不恢复 validation protocol 中已 superseded 的旧文件，也不修改 `final_frozen` 协议原文。正式 runner：

- 只允许 `--output-dir`，不接受 `--source` 或成本覆盖参数；
- 逐交易日使用 canonical `resolve_jm_contract`，区分开仓、平仓和平今费；
- 全窗口一次计算 strict vector，再按 bar 线性执行；
- 生成 report-shaped dry-run、equity/drawdown、pre-apply audit 和 hash-bound packet；
- 始终处于 PostgreSQL read-only transaction，不创建正式报告。

证据目录：[`../../../data/reports/htdy_trusted_report_x5_02/`](../../../data/reports/htdy_trusted_report_x5_02/)。Gate `HTDY_TRUSTED_REPORT_APPLY_PACKET_READY` 只表示审批包可供用户决定是否进入后续正式写入；全窗收益/回撤不构成策略可信、OOS、live 或 alert 结论。

## X5-04 OOS Fixed Runner

X5-04 已新增 HTDY 专用 file-only runner。它只选择 frozen protocol 的 `oos_fixed`，读取窗口前 72 根 passed-only 15m bar 计算 strict indicator，随后丢弃预热区 snapshot 并以全新策略状态只执行 OOS bars。预热期不允许生成信号、订单、交易、收益、持仓或 pending action。

正式 CLI 必须先验证 hash-bound 的 X5-03 `HTDY_TRUSTED_BACKTEST_CANDIDATE` 包、committed transaction、candidate/report14 双 audit 和 candidate binding snapshot。当前仓库没有该前置 Gate，因此 runner 只完成代码与测试，真实 OOS 未运行，状态为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`。

## X5-03 Trusted Backtest Candidate

X5-03 专用应用器只消费 X5-02 immutable apply packet。它先复算 packet/artifact hash，再在 canonical PostgreSQL repeatable-read 单事务中创建一个 formal task/report 与对应 trades/orders；flush 后、commit 前运行 candidate/report14 双 trust audit、report14 fingerprint、row delta、facts hash、formal lineage 和 confirmed-close/next-bar-open timing。任一失败整体 rollback，并只落盘脱敏失败证据。

task_no 由 X5-02 packet hash 派生，重复 apply 不会创建第二个 candidate。现有 schema 不保存独立 equity/metrics rows：equity 由 trades 确定性复算，metrics 保存在 report summary，packet 同时记录 equity point 和 metric field 数量。成功 Gate `HTDY_TRUSTED_BACKTEST_CANDIDATE` 仍只代表可信候选报告，不代表 OOS 通过、策略盈利、live 或交易准入。

## Validation Protocol V1（C5-01）

正式回测 / OOS **前**冻结验证口径（不假定策略有效，不执行正式回测）：

- [`VALIDATION_PROTOCOL_V1.md`](VALIDATION_PROTOCOL_V1.md)：协议说明、hard reject、E5-05/X5-05 分支。
- [`../../../configs/oos/htdy_strict_validation_protocol_v1.json`](../../../configs/oos/htdy_strict_validation_protocol_v1.json)：机器可读配置（`freeze_status=final_frozen`）。
- [`../../../configs/oos/schemas/htdy_validation_protocol_v1.schema.json`](../../../configs/oos/schemas/htdy_validation_protocol_v1.schema.json)：JSON Schema。
- [`../../../data/reports/indicator_contract_v1/htdy_validation_protocol_config_hash.json`](../../../data/reports/indicator_contract_v1/htdy_validation_protocol_config_hash.json)：配置 SHA-256 证据。
- [`../../../services/quant-api/tests/test_htdy_validation_protocol_c501.py`](../../../services/quant-api/tests/test_htdy_validation_protocol_c501.py)：schema / hash / report14 隔离回归。

Cursor preparation Gate 保留为 `CURSOR_VALIDATION_PROTOCOL_PREPARED`；X4-06 经用户批准后的最终 Gate 为 `STRATEGY_VALIDATION_PROTOCOL_FROZEN`。

## 公共指标内核关系

`docs/INDICATOR_KERNEL.md` 已建立 `Indicator Kernel V1-A`：

- `EMA10 / EMA21 / EMA60` 已进入 `packages/quant-core/guiyi_quant/indicators/` 公共内核。
- 火天大有当前只在注册表中保留 `observation_only` 风险边界。
- 公式级 Spec 已完成，原始 XMA 版本仍不得写入 `strategy_signals`、`signal_events`、正式回测报告或企业微信通知。
- 原始 observation-only PoC 已完成；strict backward-looking v1 已作为研究候选新增，并完成离线候选事件评估；不能复用原始 XMA 输出冒充可信信号。

## 任务追踪

- Issue #10：`TASK-2026-07-11-002-htdy-indicator-core.md`
- Web 交付：`TASK-2026-07-11-003-web-main-indicators.md`
