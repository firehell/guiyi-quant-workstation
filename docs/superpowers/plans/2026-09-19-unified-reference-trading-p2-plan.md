# Unified Reference Trading P2 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans，在原 Terra Medium 任务连续执行；按代码时序风险完成独立 Review，不另建用户任务。

**Goal:** 将苏冰四周期与牛哇三策略的现有历史计算接入公共 reducer，建立可恢复的纯增量适配；全量入口与增量入口共用算法且保持已有输出合同。

**Architecture:** 复用现有指标 step 状态；策略 adapter 将每根有效输入转换为公共动作/边界/估值，再调用 P1 reducer。旧 public projector 作为全量 fold 与输出兼容层，统计窗口仍调用既有统计规则。状态可在纯内存 JSON round-trip 后继续，不涉及持久数据库。

**Tech Stack:** 现有 Python/dataclass/Decimal/pytest/OpenSpec。无新基础设施。

**Spec:** [总设计](../specs/2026-09-19-unified-reference-trading-design.md)、[总计划 P2](2026-09-19-unified-reference-trading-plan.md)、当前 `openspec/specs/reference-trading/spec.md`。

## 1. 本轮事实与范围

2026-09-19 核对主树 develop `e69f026dee887f4f12a2ccf6adaaa4f9c76de4aa` 干净；P0/P1已集成。
原任务 `01a0b92e-6a59-7121-92a0-d39bb35a316c` 回报该集成点回归 215 passed。本次未重新执行这组测试。
实施者须以实际最新 develop为准，检查并发 Newow算法/页面工作，保留对方修改。

P1 实际接口而非旧设计示例：

```python
class StrategyAdapter(Protocol):
    stream: StreamIdentity
    def seed(self) -> object: ...
    def advance(self, state: object, input_batch: object) -> tuple[object, ReferenceTransition]: ...

def reduce_reference(
    state: ReferenceState, *, actions=(), boundaries=(),
    completed_bar_end=None, completed_trading_day=None,
    completed_reference_price=None,
) -> ReferenceTransition: ...
```

P2允许把 object接口收窄为泛型 Protocol和具体纯类型，并按直接parity证据修正P1缺陷。
不为迁就P1现状改变旧策略合同，也不以P1已通过测试为由忽略未覆盖边界。

范围：苏冰15m/30m/60m/1d；牛哇trend/oscillation/main-rise，对现有计算合同允许的1d/1w/60m做隔离算法验证。
数据不足或尚未对外开放周期不因此新增capability；合成fixture覆盖不能冒充生产数据验收。
仅接历史计算及纯step可恢复能力，不启用forward Runtime。HTDY仍MODEL_NOT_APPROVED。
不实现P3数据库、P4构建CLI、P5查询迁移、P6worker或P7HTDY；不改通知、下载、生产数据、发布或Runtime。

## 2. 先解决实际接口差异

| 当前实现事实 | P2处理 |
|---|---|
| 公共reducer生成自己的reference-trade ID，旧策略已有稳定ID | 内部键和公开source trade ID分开；显式保留旧entry/exit/signal/trade关系，不直接替换旧API ID |
| Newow以`exit/entry-1`计算，苏冰以`(exit-entry)/entry`计算 | Decimal运算顺序会影响尾数；显式模型数值政策复用原精度/舍入/运算顺序，不把数学等价当逐值等价 |
| P1 input hash当前只覆盖actions/boundaries | 增加completed Bar时间/交易日/估值及必要物理身份，测试无信号同身份异价格必须冲突，不能误当重放 |
| P1以一次sealed completed调用计一次持有Bar | adapter按每个有效Bar fold，不把一个N-Bar批次算作1根；CLOSE、反手和中断发生Bar的计龄按旧模型精确验证 |
| P1估值参数没有独立contract/segment身份 | 通过typed completed input补齐并验证，防止空动作旧合约价格给新OPEN估值；不能只由调用方口头保证 |
| 原Newow projector可在输入集合包含多个owner时处理 | adapter必须按真实交易时间和owner边界组织，前置预热不能占用正式水位；测试交错预热和owner重入，不静默丢弃合法输入 |
| 原边界有明确先后语义 | 保持canonical同Bar action/boundary顺序；跨owner时在权威切换点完成旧段中断，不能靠改变sequence绕过配对校验 |

修正必须先有失败行为测试，并更新相关canonical真实合同；若出现必须改变公式/收益语义才能继续的冲突，仅暂停该部分并说明，其他安全部分继续。

## 3. 适配与状态设计

建议新文件：

- `packages/quant-core/guiyi_quant/reference_trading/strategy_adapters.py`：typed输入/输出协议、最小公共适配辅助；若规模很小直接扩现有adapters.py。
- `packages/quant-core/guiyi_quant/reference_trading/subing_adapter.py`：SubingReferenceAdapter与状态，复用SubingThs15mKernel。
- `packages/quant-core/guiyi_quant/reference_trading/newow_adapter.py`：NewowReferenceAdapter，按ProductStrategy选现有step函数。
- `packages/quant-core/guiyi_quant/reference_trading/checkpoint.py`：显式版本化纯JSON状态编解码；不读取文件或数据库，不用pickle。

只有实际有职责才建文件，避免同时维持两套helper。原策略公式代码仍在原指标/策略目录。

每个adapter公开seed/advance，具体输入为经过验证的Bar、owner/计算段、质量边界、预热资格、生命周期证据和固定as_of。
具体状态包含stream/model/schema、指标状态、pairing状态、当前owner/计算段、Bar计数、reference state及有界rolling窗口。
Newow还包含escape/hint关联和initial-clear资格的必要状态；生命周期证明随固定前缀验证，不由裁剪窗口猜测。
苏冰包含MACD/EMA previous值、warm-up/readiness、owner内外资格；物理前缀只预热，不在owner外创建交易。

输出delta包含本批signals/frames/indicators（只限旧public结果所需）、changed trades/marks、hints/diagnostics和末状态。
历史结果由调用方累积，不能把所有历史bars/actions/trades重复塞进每个checkpoint。
同段advance只消费新增输入；若某算法依赖有界回看，给出确切窗口与完整性证明，禁止以任意短截窗代替递归状态。
as_of/日期窗口是查询/汇总过滤，不应破坏计算预热；旧API允许的参数与错误合同保持。

### Checkpoint最低内容与校验

- schema_version、stream identity/hash、公式/模型版本、owner/calculation segment、水位及完整指标/reference状态。
- Decimal用字符串；有时区时间用规范ISO；enum用显式值；不读取进程global、随机种子或当前时间恢复。
- 不兼容schema、缺字段、非有限数值、非法枚举、错误stream/模型或不一致OPEN关联一律拒绝。
- 编解码不改变kernel现有数值类型：既有float指标状态保留其数值语义，不能借通用Decimal规则重写指标算法。
- 持久文件格式、数据库表、进程恢复任务属于后续阶段；P2仅证明序列化后可确定性续算。

## 4. 公共接口迁移原则

保持 `subing_reference.project_reference`、`newow.product_adapters.replay_strategy` 和 `newow.reference_trades.ReferenceTradeProjector.project` 的现有对外参数及输出。
允许内部抽取纯step函数，并使原全量入口fold相同step/reducer；不得形成adapter调用旧全量函数、旧全量函数再调用adapter的循环。
建议依赖方向：底层策略step -> reference adapter/reducer -> public projection兼容层；必要时将step从旧public文件抽出到策略内部模块。
Newow chart仍可调用replay_strategy；将frame-step抽成公共纯内核，而不是为了reference迫使chart依赖交易模块。
兼容层负责旧字段、source ID、hint关联、期初归属和summary格式，不再次实现开平仓状态机。
不让跨日期/分页的裁剪改变signal ID或entry关联；OPEN mark、CLOSED return、中断null必须分别对照。

旧算法只可作为本次固定基线产生oracle；最终生产树不保留长期legacy实现或动态双跑开关。
固定oracle使用仓库fixture输入，从不可变基线提取语义断言或可读golden；禁止在测试中用新代码生成自己的expected冒充parity。

## 5. 执行步骤与每步出口

### P2.0 基线与兼容对照

- [ ] 核对任务worktree/branch、最新develop、重叠任务和P1接口；复制本计划至任务树并纳入提交。
- [ ] 跑既有苏冰/Newow参考、统计与公共reducer测试，记录baseline与代码SHA。
- [ ] 用现有fixture冻结四周期苏冰、三策略Newow的信号/交易/指标/Hint/summary/diagnostics可读oracle，明确source IDs。
- [ ] 为第2节风险写红测，分别标记已确认缺陷与待验证风险，不因任务接入扩大重构。

出口：知道哪些是原合同、哪些是公共基础缺口，不能靠重录golden制造通过。

### P2.1 必要公共修正

- [ ] typed completed identity、输入hash、计龄、稳定source身份与数值政策按失败证据最小修正。
- [ ] 测试同一无信号Bar换mark价格/交易日/合约必须拒绝，完全相同输入只返回无变化。
- [ ] 测试入场Bar/次Bar平仓/多Bar批次/同Bar反手/边界计龄，以及Decimal环境rounding变更不能改变固定模型输出。
- [ ] P1全组和现有投影回归通过；仍无任何IO。

### P2.2 苏冰适配

- [ ] 提取当前_project_reference中的kernel推进与动作转换；旧信号方向及SAME_DIRECTION记录保留。
- [ ] buy/sell反手显式拆成关联CLOSE+OPEN；source signal可相同，两个source action ID/sequence必须不同且稳定。
- [ ] 15m既有身份不变；30m/60m/1d沿现有FORMULA_VERSIONS；D1质量分段v2独立于其他v1。
- [ ] 维持34/35 Bar等实际readiness、owner外预热、PRICE_UNAVAILABLE/NONPOSITIVE_CLOSE已批准分类、重置与重新预热。
- [ ] 全量wrapper与增量均走公共reducer；现有窗口summary和期初记录不随输入切批变化。

出口：四周期逐字段parity；未知缺口仍拒绝，不因类型上有中断就自行证明缺价。

### P2.3 牛哇三策略适配

- [ ] 从replay_strategy抽取可续算的每Bar状态推进，复用趋势/震荡/主升浪的现有step及配对状态。
- [ ] 保持趋势慢线B、震荡BUILD Low/CLEAR High、主升浪MA45的reference price type与数值。
- [ ] 震荡同Bar动作顺序、warmup BUILD配对、主升浪INITIAL_CLEAR_NO_ENTRY生命周期证明、Hint绑定全部不变。
- [ ] 新旧owner与quality calculation segment切换显式重置；新合约warmup不更新旧合约交易价格。
- [ ] projector全量入口复用公共迁移；statistics独立复用，不改hint为REDUCE交易。

出口：三策略在现有允许周期上的隔离parity，chart replay输出不回归，未开放周期仍未开放。

### P2.4 状态恢复与增量证据

- [ ] 实现严格JSON round-trip，各策略state在每个关键位置序列化/恢复后继续。
- [ ] 对比整段、逐Bar、固定随机切批；合法切点含预热前后、开仓前后、同Bar动作边界、换月及缺价恢复。
- [ ] 验证prefix invariance：新数据追加不改变先前已确认主动作；重绘显示组件不参与此断言或交易推进。
- [ ] 历史修订测试从变动之前checkpoint重算至尾部，与完整重算一致；P2不实现自动检测修订/重建调度。
- [ ] 用step调用计数和state大小证明新增k根仅推进k根或声明的有界窗口；测试恢复不重放完整前缀。

出口：batch/incremental/restart一致且成本不随历史长度重复全量增长。累积输出可以增长，恢复state不能保存整个历史。

### P2.5 回归、审查与集成

- [ ] 更新公共canonical、实际capability适配状态与总计划P2勾选；不得改为持久化/Runtime已完成。
- [ ] 定向测试 -> 现有参考/策略/reader/API相关回归 -> Ruff/OpenSpec/secret/diff检查。
- [ ] 独立Review重点：运算顺序/精度、source身份、未来泄漏、owner预热、hint/计龄、hash与checkpoint验证。
- [ ] 修复确认问题并重测，精确commit/push；检查最新develop的并发改动后集成，再运行受影响回归。

## 6. 文件与验证入口

新增测试建议：
`services/quant-api/tests/reference_trading/test_strategy_parity.py`、`test_checkpoint_parity.py`、`test_adapter_incremental.py`。
公共缺陷回归补入已有test_contracts/test_reducer，不另造重复测试目录。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading \
  services/quant-api/tests/test_subing_reference_projection.py \
  services/quant-api/tests/test_subing_reference_service.py \
  services/quant-api/tests/test_subing_reference_api.py \
  services/quant-api/tests/newow/test_product_adapters.py \
  services/quant-api/tests/newow/test_reference_trades.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/newow/test_reference_statistics.py \
  services/quant-api/tests/newow/test_product_replay_invariants.py
```

实际执行前用rg确认测试路径；新增兼容风险再扩到reader/product_service/API，未改Web不机械做Web构建。
所有测试使用fixture/隔离只读输入，无真实RQData、生产DB/Redis/Canonical操作。

## 7. 交付要求

报告基线与集成SHA、三策略×周期/苏冰四周期已验矩阵、实际命令/结果、golden差异、Review结论。
明确完成的是纯历史与增量计算适配；尚未保存到数据库、未后台持续运行、未启用任何新周期/通知。
未通过的策略/周期不能因其他组合成功而标全量完成。目标为P2完整交付，不以仅新增未接入adapter结束。
