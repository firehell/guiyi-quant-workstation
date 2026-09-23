# Newow 初始无入场 CLEAR 设计

状态：实现前设计；用户已批准方案 A，并要求完成设计/计划复审后交由 Sol high 实施。
代码基线 `85b6d42f8`；初稿提交 `d7cdbb0cb`。本文件不表示功能已经实现。

## 目标

当主升浪物理合约从可用历史的首根 Bar 起即处于黄带、此前从未发生真实 `BUILD`，其后首次转为蓝带并产生
`CLEAR` 时，产品必须展示该 `CLEAR` 事实，同时明确它没有可配对入场，不制造 `BUILD`，也不生成
`ReferenceTrade`、收益、订单、成交或账户事实。

本设计解决 PT2610 周线真实序列暴露的 `NEWOW_PRODUCT_PAIRING_CONFLICT`。它不改变
`newow_main_rise_ma35_ma45_page_v1` 的 MA35/MA45 公式、部分窗口均值、黄蓝转换或参考价，不补行情，不改变
owner/segment，也不放宽正常 BUILD/CLEAR 的稳定配对要求。

## 已确认事实

- 上轮只读验收在 `as_of=2026-09-13T06:36:13+00:00` 观察到 PT2610 共 41 根同物理合约周线前缀；
  本设计审查不重新连接生产。这是固定截点 evidence，实施后须独立验证新代码。
- 首根周线的 MA35 与 MA45 相等，因此主带初始为 `YELLOW`；这不是蓝转黄，没有真实 `BUILD`。
- 第 40 根周线首次从 `YELLOW` 转为 `BLUE`，内核正确产生 `CLEAR`，但内核保存的 entry/holding 均为空。
- 当前产品 adapter 要求每个 `CLEAR` 都关联真实 eligible 或 warm-up `BUILD`，因此 fail-closed。
- 页面金样在第 45 根之前即可产生 MA35/MA45 转换；改成 45 根完整 warm-up 会改变已冻结 page-parity 公式，
  不属于本修复。

## 领域模型

### 新资格类型

在现有 `TradeEligibility` 增加：

```text
INITIAL_CLEAR_NO_ENTRY
```

该值只描述一个主动作事实：当前 `CLEAR` 是本物理 owner/segment 的完整生命周期重放中首次黄转蓝，且此前不存在真实或
warm-up `BUILD`。它不表示一笔待关闭交易，不是成交资格，也不能被解释为持仓曾经存在。

“首次”由完整重放前缀决定，不是 viewport、统计窗口、分页或 rank1 首根。reader 仍是生命周期 coverage
authority；adapter/projector 不自行访问 Catalog、不重新计算公式，也不从空 action 列表推断历史完整。

`ActionKind` 仍为 `CLEAR`。公式事实与展示动作因此保持不变，不新增伪策略动作。

### 与现有资格的区别

| 资格 | 含义 | related_build_id | ReferenceTrade |
|---|---|---|---|
| `ELIGIBLE` | 正式观察窗口内的真实动作 | BUILD 为空；CLEAR 指向真实 BUILD | 建立或关闭 |
| `WARMUP_ONLY` | rank1 前缀中真实发生的 BUILD witness | 空 | 不建立 |
| `NO_ELIGIBLE_ENTRY` | CLEAR 对应一个真实 warm-up BUILD | 指向 warm-up BUILD | 不建立，仅诊断 |
| `INITIAL_CLEAR_NO_ENTRY` | 从未观察到 BUILD 的首个 CLEAR | 必须为空 | 不建立，仅诊断 |

不复用 `NO_ELIGIBLE_ENTRY`，因为“存在真实 warm-up BUILD”与“从未存在 BUILD”是两种不同事实，必须保持可审计。

## 模块与接口

### Strategy adapter 模块

新增小型、只读的 `LifecycleReplayEvidence` 值对象：按 product/frequency/physical_contract/segment 绑定
已验证的生命周期首尾 Bar、Bar 数、完整有序输入指纹、source identity 与验证 cutoff。它不是新的 coverage
authority、数据库记录或外部证书；生产中仅由 `NewowProductReader` 在既有 MDS
`validate_contract_replay_coverage(after=None)` 成功、owner/rank1 一致性检查成功后组装。
按 owner 使用已验证物理前缀的子前缀时，必须保留生命周期起点，并重新绑定该子前缀末端、数量和指纹。

`ProductReadSet` 携带分周期 evidence；`replay_strategy(identity, bars, *, lifecycle_evidence=())`
在入口校验其身份、首尾、数量和输入指纹，并传至 `StrategyReplay`。无 evidence 的既有纯函数调用可以继续
执行普通动作，但不得生成新资格；遇到待判定初始 CLEAR 时保持 pairing conflict。不允许 `complete=True`
布尔开关或调用者根据传入首根自行补证据。单元测试使用显式 synthetic evidence factory，不冒充真实 reader 验收。
生产两个 replay 调用点必须都传递 reader evidence，不在 service 重新认定 coverage。

adapter 的主升浪转换逻辑如下：

1. `step_main_rise` 继续产生原始 `CLEAR`。
2. 存在 eligible 或 warm-up BUILD 时，沿用 `_pair_action`，行为不变。
3. 只有同 segment 从初始化到当前 Bar 一直有有效黄带、此前无任何带转换，当前内核恰好黄转蓝；不存在
   eligible/warm-up BUILD，内核输入 state 的 `last_buy_price`/`bars_since_buy` 及 signal 的
   `profit_pct`/`hold_bars` 均为空，且 Bar `observation_eligible=True`、该 segment 的 lifecycle evidence 验证通过时，创建
   `CLEAR + INITIAL_CLEAR_NO_ENTRY + related_build_id=None`。
4. 不存在 BUILD 但内核声称存在 profit 或 holding 时，视为状态矛盾并继续
   `NEWOW_PRODUCT_PAIRING_CONFLICT`。
5. 新资格仅由 `main_rise` adapter 生成；趋势和震荡的裸 CLEAR 继续 fail-closed。
6. 私有 segment-local 状态记录初始黄带资格，任何真实带转换（含 warm-up 内发生的 CLEAR/BUILD）或无效状态
   都永久消费此资格；仅在权威 segment 切换时重置。清空当前 open/prewarm 指针不能恢复它。
7. 初始 CLEAR 若发生在 `observation_eligible=False` 前缀中，只消费资格，不对外创建该 Action；后续真实
   warm-up BUILD 仍产生既有 witness。禁止重复初始 CLEAR、隐式资格重建或已关闭一笔交易后再次套用新资格。

这一 seam 保持深度：service 仅传递 reader 已验证的输入证据，不需要了解主升浪初始带状态或配对状态机。

### StrategyAction 合同

`StrategyAction` 构造时增加以下不变量：

- `INITIAL_CLEAR_NO_ENTRY` 只能用于 `ActionKind.CLEAR`；
- `related_build_id` 必须为 `None`；
- strategy 必须为 `main_rise`，sequence 必须为 0，source marker 和 source-related IDs 必须为空；
- 其他资格的既有验证与 signal ID 生成不变。

`StrategyFrame.__post_init__` 才验证 frame 上下文：completed、observation-eligible、身份/日期/时间严格匹配、
`main_state=CLEAR` 且恰好包含一次该 Action。Action 构造器不访问尚不存在的 Frame。

signal ID 继续由 identity、物理合约、segment、Bar、kind 和 sequence 构造。此前该输入会失败且没有对外 Action，
因此新 Action 不会与旧成功事实发生内容冲突。

### ReferenceTradeProjector 模块

现有 `project(replay, boundaries, as_of) -> ReferenceProjection` 接口不增加参数。投影器必须验证：

- Action 属于 `main_rise`；
- kind 为 `CLEAR`；
- `related_build_id is None`；
- replay 中存在匹配当前 owner/segment 的 reader lifecycle evidence；独立检查其身份、首尾、数量与
  frame 输入指纹，缺失、错配或裁剪后仍沿用原 evidence 一律拒绝；
- 同 owner/segment 尚无 open trade，完整 action 历史中没有 eligible/warm-up BUILD，也没有先前任何 Action；
- 该 Action 对应一个真正存在的 eligible frame，不能使用 `_validate_action` 对非 ELIGIBLE 的默认位置 0；
- 在同 segment 的完整 frame 前缀中，当前帧之前至少一帧，均有效且 `ma35 >= ma45`，当前帧有效且
  `ma35 < ma45`、`main_state=CLEAR`、参考价精确等于当前 `ma45`，并恰好包含本 Action；
- 当前 Bar 不晚于 `as_of`，且严格早于该 owner 的 effective boundary（若存在）。

上述 frame 校验只验证已有 StrategyFrame 的值与动作一致性，不再运行 MA 或另一份主升浪内核。
按 frame/action 建立一次索引，整体 O(N+M)，避免每个 CLEAR 重扫全部历史。纯函数只验证 evidence 与输入绑定，
不自行证明 Catalog 真伪；真实 coverage 仍由唯一 MDS 校验。接口现在明确拒绝缺证据或截断输入，不能仅以
文档前置条件代替检查。针对 as-of 的合法子前缀必须从已验证输入派生 evidence，保持原生命周期首端，重新绑定
截至 cutoff 的末端/数量/指纹；不能任意裁掉左侧历史。未来后缀内容不参与当前策略判定与诊断。

全部成立时，投影器：

- 不创建、关闭或修改任何 `ReferenceTrade`；
- 在 projection diagnostics 中保留一次 `INITIAL_CLEAR_NO_ENTRY`；
- 继续处理后续 Action，因此后续真实 BUILD/CLEAR 可形成正常交易。

任一条件不成立时继续抛出 `NEWOW_REFERENCE_PAIRING_CONFLICT`。owner boundary、rollover interruption、
Decimal 收益和统计逻辑不变。

和既有 `NO_ELIGIBLE_ENTRY` 一样，先剔除上游未经验证的同名诊断，只由 projector 在验证动作后重新加入。
未来 Action/Frame 不参与当前时点诊断、历史首次判定或交易状态。prefix 与同一 as-of 全量 replay 的结果必须一致。
跨 segment 重置，旧合约的 BUILD 不可配对新合约初始 CLEAR。无需新增持久化状态、snapshot 文件或数据库表；
进程重启仍通过已有完整 replay 恢复，现有内核序列化保持原合同。

### Typed API 与 Web

Typed API action envelope 扩展 `trade_eligibility` 的允许值。Web 严格 parser 同步接受该值，并把它保留到
`NewowProductActionMarker`，避免展示层丢失语义。

图表仍绘制 `CLEAR` 向下动作 Marker；该资格的文字为“清仓（无入场）”。动作详情必须显示：

```text
初始无入场：未观察到可配对 BUILD，不生成参考交易。
```

Reference 面板不创建占位交易、不显示这条 Action 的单笔零收益，也不把它计入
closed/open/interrupted/initial-before-window 统计。仅含该 Action 时各交易数为 0，win rate、mean 和
sum return 均沿用 `_closed_metrics(())` 的 `None`，Web 展示既有空值文案。该事实与“统计窗口开始前
已存在的真实交易 initial_before_window”严格区分。后续存在合法交易时正常统计，不把整个 segment 标成零交易。

主图 Marker、动作选择详情与参考空态必须可到达；Web 不重建入场也不验证全生命周期，parser 只检查 envelope、
strategy/kind/eligibility/关联字段/Bar/sequence 的结构一致性。不要要求裁剪图表页中存在初始前缀。

## 版本身份

这是 typed product 与 ReferenceTrade 投影合同的可观察变化，必须显式升级：

```text
newow_product_detail_v1
→ newow_product_detail_v2

newow_marker_reference_zero_cost_v1
→ newow_marker_reference_zero_cost_v2
```

`newow_main_rise_ma35_ma45_page_v1` 与全部公式版本保持不变；
本设计当时保留 `newow_futures_segment_interrupt_v1`，因为它不改变换月中断规则；后续严格无交易日输入适配
已按 active canonical 升级为 `newow_futures_segment_interrupt_no_trade_v2`。

新的 reference model version 参与 ReferenceTrade ID、snapshot/cache identity 和 Web 兼容性判断。旧 typed v1
响应不得被 v2 客户端静默接纳，旧 snapshot token/cursor 不得跨版本复用。旧固定 `/trend-detail` D1 接口不变。

现有 reference version 是三策略共享常量，故 v2 会使三策略所有新计算的 ReferenceTrade ID 更新；相同
BUILD signal ID、公式数值、配对与收益不变。同版本内 viewport/OPEN→CLOSED 身份稳定。无需迁移生产表，
因为 ReferenceTrade 是只读可重算投影；历史 evidence 保持原 v1，不批量改写旧报告。

`_dependency_proof` 已含 reference version；实施仍须将 schema/reference/futures-adaptation 的合同组加入
`_page_identity`（chart、reference 两类 cursor 都依赖它）以及 cache common identity，实际测试旧 cursor
在无 snapshot token 时也被拒绝。输入内容 hash 保留输入事实语义，无需为版本变化伪装成行情变动。
Web 请求 generation、selected signal/trade、历史定位和跨面板兼容状态随合同组变化一起失效。

API 与 Web 必须成套构建和发布；旧 Web 对 v2、新 Web 对 v1 均明确拒绝，不能持有旧结果继续显示为当前。
版本回退也须成套且清理进程内缓存；这里仅定义兼容合同，不执行发布。capability v1、historical selection v1、
策略 profile v1、主动作/Hints ID 保持不变。active OpenSpec 的 MACD 小节所说顶层 v1 兼容须随本改动明确
更新为“MACD 分支形状保持，顶层由本次 v2 演进”，避免自相矛盾。

## 错误与安全边界

- 只有经过全部结构验证的初始无入场 CLEAR 才从内部冲突转为 typed Action。
- 伪造 related ID、用于 BUILD、用于非主升浪、位于已有 Action 之后或与 open trade 并存时继续 fail-closed。
- 未预期异常仍只公开 `NEWOW_INTERNAL_ERROR`，不透传内部异常、路径、SQL 或凭据。
- 不读取 provider，不修改 Catalog/Canonical/metadata，不发送通知，不启用 Runtime，不创建订单。
- 当前 PT 数据写入授权已消费；实现验证只允许读取现有 Catalog/Canonical。

## 验证设计

实现必须按 TDD 完成下列行为验证：

1. 主升浪从初始黄带到首次蓝带时产生稳定 `CLEAR + INITIAL_CLEAR_NO_ENTRY`，没有伪 BUILD。
2. 同一 replay 的 ReferenceProjection 为零交易，diagnostics 精确包含 `INITIAL_CLEAR_NO_ENTRY`。
3. 后续真实 BUILD/CLEAR 仍产生一笔正常 CLOSED ReferenceTrade。
4. 新资格用于 BUILD、其他策略、带 related ID、已有 warm-up/eligible BUILD 或非首个 Action 时均 fail-closed。
5. 现有 warm-up BUILD → `NO_ELIGIBLE_ENTRY` CLEAR 语义保持不变。
6. API 序列化返回 v2 schema/reference version 与新资格；旧 v1 envelope 被 v2 Web parser 拒绝。
7. Web 显示 CLEAR Marker 和“清仓（无入场）”说明，不产生 ReferenceTrade 行或收益。
8. 固定 PT 周线只读 matrix 中 trend、oscillation、main_rise 三个 main case 均不再因 pairing conflict 失败；
   该验证不外推全 60 品种完成。
9. 未来初始 CLEAR 不泄露诊断；完整 replay 的早期 as-of 与相应 prefix 结果一致；历史裁剪仅在完整投影后发生。
10. 旧 token、chart/reference cursor、旧版本迟到响应不能污染 v2；同版本历史定位/分页兼容性保持。
11. warm-up 初始 CLEAR 只消费资格且不输出；后续 warm-up BUILD → rank1 CLEAR 才使用
    `NO_ELIGIBLE_ENTRY`；换 owner 后独立判定。
12. 裸 tuple 或截断前缀不能声称完整生命周期；reader 验证成功的完整前缀经 service 产生新资格，coverage
    失败、evidence 错配、复用旧 evidence、action-only replay 均 fail-closed。

定向验证通过后，扩展运行 Newow Core/API/Web 相关测试、类型检查、构建、OpenSpec、仓库一致性、secret scan
与 diff check，并由同一位独立 reviewer 复核 exact commit。

## 交付与 Gate

实现允许连续完成代码、测试、独立 Review、task commit 以及条件满足的本地 develop 集成。此前针对本任务
含生产证据的远端 push 曾被自动审批拒绝；owner 已于 2026-09-23 确认本仓库 origin 及常规文档/`develop` push 授权，后续按 `AGENTS.md` 执行。
main/tag/Release、Runtime、生产写入和通知按独立 Gate 处理。真实 PT 只读验收若权限不可用，先完成全部离线
实现/Review，明确保留现场验收未完成，不能凭旧回执宣称成功。

集成顺序固定为：已包含 `codex/ui-unification@a755b0694` 的 develop → 趋势点依赖
`codex/newow-trend-channel-points@faa963d2a717f4cd2127ca8edb145ad9f1352afa` → 本次 CLEAR v2。
该提交替代初审的 `a83dd60e`：补齐重复时间掩盖乱序的 fail-closed 检查，并明确 timeline merge seam；不变更本设计目标。
Sol 新隔离分支先核对当前 develop 是否已包含趋势点 exact commit；已包含则直接使用，否则在本实施分支
显式引入该提交并保留其变更，不修改其他任务工作树。它作为前置依赖同样须有 Review/测试证据，不因引入即
宣布通过。涉及 API schema、product_service、Web parser/primitives/composable、OpenSpec 的 v2 修改必须在
该依赖整合后进行；最终复测全部重叠路径。若依赖被作者修订，先协调确认替代 commit，独立 Core 工作可继续。
无需重做整页布局、主状态公式或扩建账户链路，不清理其他任务或复用其服务端口。

本设计/计划存放于 `docs/tasks/newow-initial-clear/`，现由 active OpenSpec、DECISIONS、PROJECT_SOURCE、
实现代码与 Git history 共同承接；STATUS 只记录真实完成级别，不保留第二套 active 产品 authority。
