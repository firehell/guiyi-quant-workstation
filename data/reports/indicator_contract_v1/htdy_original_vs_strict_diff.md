# HTDY 原始公式、Web 与 Strict 差异审计

审计任务：`HTDY-SOURCE-XMA-AUDIT-400`
最终 Gate：`HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`

## 1. 审计对象

| 对象 | 代码/规范锚点 | 当前角色 |
|---|---|---|
| 用户原始公式归档 | `docs/strategy_specs/htdy/INDICATOR_SPEC.md:19-108` | canonical source text；45 条可执行赋值/输出/绘图语句 |
| Python original PoC | `experiments/htdy_indicator/htdy_original_core.py:218-330` | `huotian_dayou_original_v0`，observation-only |
| Web original overlay | `apps/quant-web/src/utils/indicators.ts:60-129,131-164,235-349` | original 的部分观察展示；当前 main indicator registry 仍禁用 HTDY |
| strict research core | `experiments/htdy_indicator/htdy_strict_core.py:79-169` | `huotian_dayou_strict_v1` 因果研究候选 |
| strict strategy candidate | `packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/vnpy_strategy.py:644-705,778-802` | dry-run formal backtest candidate；不是正式策略准入 |

逐条覆盖见 `htdy_source_formula_map.csv`。canonical 公式共 45 条逻辑可执行语句；多行 `黄K`（物理行 59-61）合并为一条逻辑映射，注释和分隔线未计入。

## 2. 能力矩阵

| 能力 | original v0 | Web overlay | strict v1 / `火天大有（因果改写）` |
|---|---|---|---|
| 公式身份 | 原始公式 observation PoC；XMA(25) 已确认不等价 | 与 Python 相同的 observation approximation | 独立 causal adaptation |
| 核心平滑 | 双层仓库 XMA `[-13,+11]` | 与 Python 相同；均有 off-by-one | trailing double EMA，SMA-window seed |
| 未来引用 | 是 | 是 | 未在已覆盖字段中发现 |
| 历史重绘 | 是 | 是 | 已有 future-tail/append 测试未发现 |
| DDX/V2/V5/V10/V20 | 已实现，含 `FROMOPEN` 标量近似 | 未实现 | 明确排除 |
| DY/DY2/XG2 | 已实现，但 DY 批量语义与原式不等价 | 明确不展示 XG2 | 明确排除 |
| 背景/板块文本 | 未实现 | 未实现 | 不适用 |
| 通道/色带/K 线绘制 | 输出数值/布尔，不直接绘图 | 部分实现为 SVG/图层观察 | 只产出候选字段，不接 Web |
| 正式回测 | 禁止 | 禁止 | formal candidate only；未获得 Stage 5 准入 |
| live / alert / 通知 | 禁止 | 禁止 | 禁止 |

## 3. 已确认差异

### 3.1 XMA(25) 已确认不等价，XMA(6) 仍 unresolved

Python `xma` 与 Web `tdxXma` 使用完全相同的自定义 NumPy-like slice：偶数周期加 1，25 周期单层名义偏移 `[-13,+11]`，6 周期归一为 7 后偏移 `[-4,+2]`，窗口丢弃非有限值，序列尾部用缩短窗口继续计算。双层依赖分别扩大到 `[-26,+22]` 和 `[-8,+4]`。

2026-07-19 用户提供 `JM2609_火天大有逐点数值.xlsx`（SHA-256 `e289cce7b61269ebacce6a8c7587afa87234bf00f925892968aa0ae2b39af5c3`），含 840 行日粒度 OHLCV、ZK1/ZD1/ZD2 及买多/卖空预警。稳定区间 780 行逐点比较显示：

- 当前仓库 `[-13,+11]` 的 ZK1/ZD1 两位小数匹配均为 `0/780`，MAE 分别为 `9.141588 / 8.600512`；
- 对称 `[-12,+12]` 的 ZK1/ZD1 两位小数匹配为 `771/780 / 768/780`，最大绝对误差仅 `0.005600 / 0.005200`；
- 最后 24 行对称候选 ZK1/ZD1 两位小数均 `24/24` 匹配；全部 840 行买多/卖空预警均逐行一致，事件数分别为 `17 / 10`。

因此 workbook 足以在等权 25 点偏移均值候选中确认窗口偏移是对称 `[-12,+12]`，并确认当前 Python/Web 有一根 bar 的 off-by-one。它没有 XMA(6) 或 VAR23 中间值，也缺少直接内层 XMA、客户端版本和执行公式 hash，不能关闭完整 XMA Gate。详细证据见 `htdy_xma_semantics.md`。

### 3.2 Web 是有意裁剪的观察层

Web `calculateHuoTianDaYou` 实现通道、`ZD2`、黄/白 K、三连观察、`VAR23/回调买/XG` 和绘图段（`indicators.ts:60-164`）。它没有实现背景、板块信息或完整通达信绘图指令，并有意排除 `DDX/V2/V5/V10/V20/DY/DY2/XG2`。`apps/quant-web/tests/indicators.test.ts:126-132` 明确断言 `xg2Observation` 不存在。

因此 Web 不是完整原公式执行器；在 XMA(25) off-by-one 修复并建立 golden vector 前，它只能称为 original-v0 observation approximation。当前 `mainIndicators` registry 仍令 HTDY `available=false`、`alertCapable=false`，不应把工具函数存在解释为 active/formal capability。

### 3.3 Python PoC 的 DY 与 FROMOPEN 是近似而非等价

- 原式 `DY:=CURRBARSCOUNT=1 AND C<REF(C,1)` 只有图表末 bar 可能为真。Python `dy = c < prev_close`（`htdy_original_core.py:274`）把每个历史下跌行都当作图表最后一行；metadata `each_row_treated_as_chart_last_bar_for_poc` 仅披露该假设。这会改变 `DY2` 与 `XG2` 历史序列。
- 原式 `FROMOPEN` 是逐时刻距开盘分钟。Python 使用全序列单一标量，默认 `1.0`（`:227,271,317`），没有期货夜盘、午休、周期和交易日历语义。

这两个差异足以使 original Python 的资金/XG2 区块不能被视为公式等价，即使以后解决 XMA 数值边界也仍需独立 oracle。

### 3.4 Strict 是因果改写，不是公式等价

strict 在通道和 `VAR23` 中把双层 XMA 替换为 trailing double EMA（`htdy_strict_core.py:104-127,172-200`；strategy 副本为 `vnpy_strategy.py:674-693,778-802`）。该 EMA：

- 只读取当前与过去 bar；
- 每层等待完整有限窗口后用 SMA seed；
- 遇到无效当前值时保留该点 NaN，不向未来取值；
- 数值目标不是复刻 original XMA。

strict 明确排除 `DDX/V2/V5/V10/V20/DY/DY2/XG2`（`htdy_strict_core.py:157`）。保留的黄/白 K、三连与 XG 只是把原条件应用于新通道/新 VAR23，因输入数值已经改变，事件也可能与原式不同。

正式展示名称应为：

```text
火天大有（因果改写）
```

不得以“火天大有原版”“通达信等价版”或其他容易混淆的名称发布 strict。

## 4. Confirmed-bar 与未来尾部

- original/Web：bar 已确认并不充分。当前位置的双层 XMA 仍读取后续 bar；追加/修改未来尾部会改变已确认历史点。测试锚点：`test_htdy_original_poc.py:86-109` 与 `apps/quant-web/tests/indicators.test.ts:134-147`。
- strict core：现有 `test_htdy_strict_core.py:48-123` 覆盖 warm-up NaN、future-tail invariance 与 prefix/batch append consistency。
- strict strategy candidate：`test_htdy_formal_backtest_candidate.py:140-168` 另行确认未来尾部不改变先前输出，并在 `:171-189` 确认收盘 bar 产生候选、下一 bar open 才成交的时点分离。

这些测试支持“当前 strict 实现是因果候选”，不支持通达信数值等价、样本外有效、正式报告可信、live 或 alert readiness。

## 5. 安全问题分级

### P0

1. original/Web 双层 XMA 使用未来 bar并重绘，必须保持 `observation_only`，不得进入正式回测、信号、live、alert、企业微信或订单。
2. numeric oracle 已确认 Python/Web XMA(25) off-by-one；修复前不得把当前实现称为通达信原版或忠实复现。
3. XMA(6)/VAR23、直接内层字段和 oracle provenance 仍 unresolved，最终 Gate 必须保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。
4. Python `DY` 和 `FROMOPEN` 不是原公式图表/时间语义，禁止把 original-v0 资金/XG2 输出用作正式证据。

### P1

1. strict 需以独立名称 `火天大有（因果改写）` 和独立版本展示，明确写为 causal adaptation。
2. Stage 5 前必须重新执行 confirmed-only、无未来引用、future-tail 稳定性，并审查 Profile lineage、成交时点、手续费、滑点、乘数、保证金、单笔风险、最大回撤和连续亏损。
3. Web 若未来启用 strict renderer，必须新增独立 registry/capability contract，不能复用 original-v0 的 `htdy` 身份静默切换算法。

### P2

1. 以本次 XMA(25) 对称窗口为修复依据，但必须先建立 Python/Web golden vector，再迁移 original observation 调用方；不得原地静默改变旧截图或历史观察语义。
2. 再导出 XMA(6)、VAR23、直接内外层 XMA(25) 与预热历史，关闭剩余 Gate。
3. 若以后研究资金区块，先定义期货 `FROMOPEN`、`CURRBARSCOUNT`、confirmed-bar 与夜盘语义，再新建版本，不能补丁式恢复 XG2。

## 6. Gate 与继续建议

本次允许合并三份只读审计报告，但只得到：

```text
HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED
```

以下只作为 evidence components，不作为 D4-00 pass Gate 发出：

| Evidence component | 状态 |
|---|---|
| `HTDY_SOURCE_FORMULA_FROZEN` | `EVIDENCE_CONFIRMED_NOT_GATE` |
| `HTDY_XMA25_WINDOW_OFFSET_AUDITED` | `EVIDENCE_CONFIRMED_NOT_GATE` |
| `HTDY_REPOSITORY_ORIGINAL_V0_XMA25_NOT_EQUIVALENT` | `EVIDENCE_CONFIRMED_NOT_GATE` |
| `HTDY_ORIGINAL_STRICT_BOUNDARY_DEFINED` | `EVIDENCE_CONFIRMED_NOT_GATE` |

由于完整三项 pass 条件没有同时满足，本任务只发出阻断 Gate，不发出任何部分 pass Gate。

不得宣告：

```text
HTDY_FORMULA_SOURCE_AUDITED
XMA_SEMANTICS_MATCHED
HTDY_STRICT_READY_FOR_FORMAL_BACKTEST
HTDY_FORMAL_REPORT_READY
HTDY_OOS_READY
HTDY_LIVE_READY
HTDY_ALERT_READY
```

`original_v0` 继续 `observation_only`，无 formal backtest/live signal/alert capability。`strict_v1` 继续只是 formal candidate；当前代码和测试可以保留，但不能据此越过 Stage 5。

`D4-01` 对 EMA/MACD/ATR 等非 HTDY 调用方仍有效；`caller_inventory.csv` 与 `policy_matrix.csv` 中的 HTDY readiness 行，在 D4-00 blocked 期间只应解释为 provisional 风险盘点，不构成 formal 准入。
