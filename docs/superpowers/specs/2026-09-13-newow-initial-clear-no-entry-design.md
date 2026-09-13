# Newow 初始无入场 CLEAR 设计

## 目标

当主升浪物理合约从可用历史的首根 Bar 起即处于黄带、此前从未发生真实 `BUILD`，其后首次转为蓝带并产生
`CLEAR` 时，产品必须展示该 `CLEAR` 事实，同时明确它没有可配对入场，不制造 `BUILD`，也不生成
`ReferenceTrade`、收益、订单、成交或账户事实。

本设计解决 PT2610 周线真实序列暴露的 `NEWOW_PRODUCT_PAIRING_CONFLICT`。它不改变
`newow_main_rise_ma35_ma45_page_v1` 的 MA35/MA45 公式、部分窗口均值、黄蓝转换或参考价，不补行情，不改变
owner/segment，也不放宽正常 BUILD/CLEAR 的稳定配对要求。

## 已确认事实

- PT2610 在固定 as-of 下共有 41 根同物理合约周线前缀。
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

该值只描述一个主动作事实：当前 `CLEAR` 是本物理 owner/segment 中第一个可见主动作，且此前不存在真实或
warm-up `BUILD`。它不表示一笔待关闭交易，不是成交资格，也不能被解释为持仓曾经存在。

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

现有 `replay_strategy(identity, bars) -> StrategyReplay` 接口不增加参数。复杂性留在主升浪 adapter 实现中：

1. `step_main_rise` 继续产生原始 `CLEAR`。
2. 存在 eligible 或 warm-up BUILD 时，沿用 `_pair_action`，行为不变。
3. 不存在任何 BUILD，且内核 `profit_pct is None`、`hold_bars is None` 时，创建
   `CLEAR + INITIAL_CLEAR_NO_ENTRY + related_build_id=None`。
4. 不存在 BUILD 但内核声称存在 profit 或 holding 时，视为状态矛盾并继续
   `NEWOW_PRODUCT_PAIRING_CONFLICT`。
5. 新资格仅由 `main_rise` adapter 生成；趋势和震荡的裸 CLEAR 继续 fail-closed。

这一 seam 保持深度：调用方仍只需重放策略，不需要了解主升浪初始带状态或配对状态机。

### StrategyAction 合同

`StrategyAction` 构造时增加以下不变量：

- `INITIAL_CLEAR_NO_ENTRY` 只能用于 `ActionKind.CLEAR`；
- `related_build_id` 必须为 `None`；
- 其他资格的既有验证与 signal ID 生成不变。

signal ID 继续由 identity、物理合约、segment、Bar、kind 和 sequence 构造。此前该输入会失败且没有对外 Action，
因此新 Action 不会与旧成功事实发生内容冲突。

### ReferenceTradeProjector 模块

现有 `project(replay, boundaries, as_of) -> ReferenceProjection` 接口不增加参数。投影器必须验证：

- Action 属于 `main_rise`；
- kind 为 `CLEAR`；
- `related_build_id is None`；
- 同 owner/segment 尚无 open trade、eligible BUILD 或 warm-up BUILD；
- 它是该 owner/segment 的第一个已输出 Action。

全部成立时，投影器：

- 不创建、关闭或修改任何 `ReferenceTrade`；
- 在 projection diagnostics 中保留一次 `INITIAL_CLEAR_NO_ENTRY`；
- 继续处理后续 Action，因此后续真实 BUILD/CLEAR 可形成正常交易。

任一条件不成立时继续抛出 `NEWOW_REFERENCE_PAIRING_CONFLICT`。owner boundary、rollover interruption、
Decimal 收益和统计逻辑不变。

### Typed API 与 Web

Typed API action envelope 扩展 `trade_eligibility` 的允许值。Web 严格 parser 同步接受该值，并把它保留到
`NewowProductActionMarker`，避免展示层丢失语义。

图表仍绘制 `CLEAR` 向下动作 Marker；该资格的文字为“清仓（无入场）”。动作详情必须显示：

```text
初始无入场：未观察到可配对 BUILD，不生成参考交易。
```

Reference 面板不创建占位交易、不显示零收益，也不把它计入 closed/open/interrupted 统计。

## 版本身份

这是 typed product 与 ReferenceTrade 投影合同的可观察变化，必须显式升级：

```text
newow_product_detail_v1
→ newow_product_detail_v2

newow_marker_reference_zero_cost_v1
→ newow_marker_reference_zero_cost_v2
```

`newow_main_rise_ma35_ma45_page_v1` 与全部公式版本保持不变；
`newow_futures_segment_interrupt_v1` 保持不变，因为本设计不改变换月中断规则。

新的 reference model version 参与 ReferenceTrade ID、snapshot/cache identity 和 Web 兼容性判断。旧 typed v1
响应不得被 v2 客户端静默接纳，旧 snapshot token/cursor 不得跨版本复用。旧固定 `/trend-detail` D1 接口不变。

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

定向验证通过后，扩展运行 Newow Core/API/Web 相关测试、类型检查、构建、OpenSpec、仓库一致性、secret scan
与 diff check，并由同一位独立 reviewer 复核 exact commit。

## 交付与 Gate

实现完成只允许形成 task commit 和 develop 候选。普通本地 develop 集成仍需满足测试与 Review；远端 push
因包含生产证据须取得明确授权。main merge、tag、Release、Runtime promotion、真实数据写入和通知均为独立 Gate，
本设计不授权这些动作。
