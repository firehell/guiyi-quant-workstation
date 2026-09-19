# 苏冰 D1 质量分段与重新预热提案

状态：`PRODUCTION_APPLIED / FIXED_CUTOFF_ACCEPTED / DEVELOP_INTEGRATION_READY`

固定影响盘点截止：`2026-09-18T18:30:00+08:00`

证据提交：`e45fca24b8691b13314cfecb2559b9251dd823fb`

本文件记录已批准的业务合同和实现边界。生产应用已按精确计划单次执行；本文件不授权后续
Runtime、Scope、通知、release 或 provider 操作。

## 1. 当前结论

生产应用后的固定截止结论为 `240/240` 数据/API/页面可加载。研究状态独立保持为 15m 60 ready，
30m 与 60m 各 59 ready + 1 warming，1d 59 `CROSS_EVALUATED` + RS `WARMING`。来源复验闭合的
异常没有被改写为 OHLC，而是按已批准合同成为显式 calculation break；RS 因有效日线不足仍未进入策略可评价状态。

owner 已批准**方案 2：D1 显式质量分段和重新预热**作为候选版本合同。其核心是：

1. Market Fact 保存来源异常以及完整端点身份，不把异常行变成价格 Bar；
2. 已由唯一质量权威分类的异常端点成为显式 calculation break；
3. 每个 break 后，苏冰内核以全新状态在同一物理合约内重新预热；
4. 只有连续 34 根有效 Bar 后指标 ready，第 35 根才具有 previous DIF/DEA，可评价 exact CROSS；
5. 未知缺口、Map/Session 冲突、identity 冲突和未授权异常类型继续整体 fail closed；
6. 参考交易在质量 break 处中断，不制造平仓价和收益；K 线及指标不跨 break 连线。

固定输入下的只读设计影响估算为：16 个品种的最新 owner 有潜在可评价区间；RS2701 只有 3 根连续有效
D1，仍在预热。该估算不等于真实 ready，不证明页面验收，也不授权数据发布。

机器盘点见
[`d1-quality-segmentation-impact-proposal.json`](../../../outputs/subing-four-period-readiness-20260918/d1-quality-segmentation-impact-proposal.json)。

## 2. 当前事实与缺口

### 2.1 已有可复用能力

- `MarketDataService.read_physical_daily_quality` 已能把 exact `PRICE_UNAVAILABLE` 事实与正常 D1 Bar 分开读取。
- `PriceUnavailableFact` 只接受 `O=H=L=0、close>0、volume>0` 且证据身份完整的已批准分类；它不产生
  CanonicalBar。
- Newow 已有同合约 calculation segment、`DATA_INTERRUPTED` 和 break 后重预热语义，可参考其合同，
  但苏冰不能直接复用 Newow 公式、身份或收益模型。
- 苏冰唯一公式权威仍是 `SubingThs15mKernel`。D1 只更换公式身份为 `subing_ths_1d_v1`，参数仍按 Bar
  数计算；数学公式不变。

### 2.2 当前阻塞根因

- 7 项 exact `PRICE_UNAVAILABLE` 已有 Catalog `source_quality` 事实，但苏冰历史参考仍走严格 physical
  replay，不能消费带质量断点的完整端点序列。
- 10 项非正 Close 目前作为旧 Canonical 行触发投影冲突；虽然来源证据已经闭合，现行
  `PriceUnavailableFact` 合同不允许把它们改写成质量 break。
- OI2609/PF2609 九月各自是有效与非正 Close 混合的来源窗口。现行硬校验不能发布该混合分区，也不能只取
  8 个正 OHLC 端点后谎称分区完整。
- 当前 `ReferenceTrade` 只有 `ROLLOVER_INTERRUPTED`，没有苏冰专属的质量中断身份和统计口径。

## 3. 方案比较

### 方案 1：维持完整物理生命周期硬阻塞

保持现有 MDS、苏冰 reader、公式和参考模型不变。17 项继续 blocked；已经完成的 223 项可独立保留现有
验收事实，但是否以 223 项作为草稿 PR 的集成范围，需要 owner 单独决定。

优点：零语义变化，风险最低。缺点：任何生命周期内已证实的历史来源异常都会让整个 D1 参考面不可用，
无法表达“异常前事实、明确断点、重新预热后的有效区间”。

### 方案 2：新版本显式质量分段（推荐）

增加 D1 quality endpoint union，使每个 Calendar/Session expected endpoint 精确落在以下互斥集合之一：

```text
ValidCanonicalBar
| ProvenPriceUnavailableBreak
| ProvenNonpositiveCloseBreak
```

只有已由共享 Market Fact authority 分类并带来源证据身份的后两类可成为 break。消费者得到完整端点序列后，
将正常 Bar 划为最大连续 calculation segment；每个 break 丢弃指标状态并开始新的预热。

优点：保留来源事实、可恢复 break 后的真实有效区间、不会造价。缺点：需要新数据质量类型、D1 分区发布合同、
MDS typed seam、苏冰参考模型版本和页面表达，属于 owner 必须批准的业务合同变化。

### 不建议的缩小方案

只让苏冰读取现有 7 项 `PRICE_UNAVAILABLE`，暂不处理 10 项非正 Close，可以验证 UI 和重预热机制，
但会形成两套 D1 异常语义，并不能完成 17 项。因此它只适合作为方案 2 的隔离 fixture 阶段，不能成为正式
产品合同或验收口径。

## 4. 推荐合同

### 4.1 唯一质量权威与分类

质量分类只能发生在 `RQData adapter -> hard validation -> Canonical/Catalog publication` 的共享
Market Fact 边界。苏冰 reader、Kernel、API 和 Web 不得自行检查数值后决定 break。

| 输入事实 | 正式分类 | 是否可形成 break | 行为 |
|---|---|---:|---|
| `O=H=L=0, close>0, volume>0` 且 exact 证据完整 | `PRICE_UNAVAILABLE` | 是 | 保留来源质量事实，不生成 Bar |
| `close<=0` 且 exact 证据完整 | 新版本 `NONPOSITIVE_CLOSE` | owner 批准新合同时才是 | 保留来源质量事实，不生成 Bar |
| 全零价格行 | `NONPOSITIVE_CLOSE`，不能叫 `NO_TRADE` | 同上 | 不能生成平价 Bar、不能当休市日 |
| 正 Close 但 O/H/L 不可用 | 仍按完整 OHLC 硬合同处理 | 仅 exact `PRICE_UNAVAILABLE` 形态 | 不能因苏冰只用 Close 放宽 |
| expected endpoint 缺失且无权威分类 | `UNKNOWN_MISSING` | 否 | fail closed |
| Calendar、Session、Map、owner、重复或 source identity 冲突 | 对应结构冲突 | 否 | fail closed |

`NO_TRADE` 只能来自既有、独立且权威的业务事实，不能由价格全零推导。

### 4.2 Market Fact 与计算段分离

完整物理生命周期 provenance 证明每个 expected endpoint 是 Valid Bar 或已证实 break。它不要求单个连续
指标状态贯穿整个生命周期。

计算段是同一物理合约内、两个 break 之间的最大连续 Valid Bar 序列：

```text
physical_contract + authoritative_owner_start
  -> owner_segment_id
  -> calculation_segment_id = hash(frequency, contract, authoritative_owner_start, preceding break boundary, quality policy version, first valid Bar)
```

- rank1 owner segment 与 calculation segment 是两个身份；同一 owner 可以包含多个 calculation segment。
- 本合同的 `frequency` 固定为 `1d`。owner 身份绑定权威 owner 起点；calculation 身份绑定其前置不可变 break
  及首根有效 Bar。owner 终点、未来追加映射和全局变化 revision 不进入历史段身份，确保 prefix invariance。
- break 后不得继承 EMA12、EMA26、DEA9、EMA21、previous DIF/DEA 或未平参考。
- 物理换月始终重置，即使前后都没有质量 break。
- 同一合约以后再次成为 rank1，只能使用该合约最近 break 后的连续有效前缀；新的 owner segment 不继承旧
  owner 的参考交易。
- batch、incremental 和 restart 必须由相同 endpoint union 与相同排序生成相同 calculation segment id、
  指标值和状态。prefix 尾部追加不得改变已完成段的历史输出。

### 4.3 预热和第一根可评价 Bar

所有周期继续使用现有 `sma_window` seed：

- 第 26 根有效 Bar 首次得到 slow EMA；
- 第 34 根首次同时得到 DEA9、MACD 和 EMA21，Kernel 为 ready；
- 第 34 根之前没有 previous ready DIF/DEA；
- 第 35 根才可使用第 34 根 previous state 评价 exact CROSS。

所以 API/Web 必须冻结为三态：第 1–33 根为 `WARMING`；第 34 根为
`INDICATOR_READY_CROSS_UNEVALUABLE`，表示指标已经 ready、但尚无前一 ready 状态可比较；第 35 根开始为
`CROSS_EVALUATED`。任何 `WARMING` 或 `INDICATOR_READY_CROSS_UNEVALUABLE` 都不能显示为“无信号”。

### 4.4 苏冰公式和周期隔离

- `subing_ths_15m_v3`、现有 Rule、Scope、Event、formatter、通知和 Runtime 完全不变。
- D1 使用新数据质量合同和新的参考模型版本，但公式身份保持 `subing_ths_1d_v1`；不得修改 exact CROSS、
  EMA21 或 seed。
- 30m、60m、15m 不自动采用 D1 break 合同。若未来需要，必须按各自 physical 1m/聚合 provenance 和周期
  单独设计、版本化和验收。
- 通用 MDS 新类型必须是显式 opt-in typed seam；普通 strict reader 继续遇到 break 就失败，避免改变其他
  consumer 或已退役品种行为。

### 4.5 参考交易和统计

建议新增参考模型身份 `subing_reference_reverse_close_quality_segment_v2`，保留 v1 结果不可变。

质量 break 行为：

- 未平交易变为 `DATA_INTERRUPTED`，与 `ROLLOVER_INTERRUPTED` 分开；
- `exit_signal_id`、`exit_bar_end`、`exit_reference_price` 和 `reference_return_pct` 必须为空；
- `holding_bars` 只计入 entry 到 break 前最后一根有效 Bar；
- 可保存并显示“最后有效标记价/时间”，但必须标明它不是当前浮动或退出价；中断交易的当前浮动为空；
- break 后的新 calculation segment 可以独立产生新交易，不能用后续 CLEAR/反向信号关闭 break 前交易；
- 窗口开始前已开且仍连续的交易标为 initial；窗口前已经中断且 break 不在窗口内的记录不进入本窗口；
- `closed/open/initial/data_interrupted/rollover_interrupted` 分别统计，收益汇总只包含窗口内新开且 CLOSED 的
  交易。中断、OPEN、initial 不进入胜率、均值或收益百分点合计。

### 4.6 K 线、指标、信号和当前状态

- K 线返回可用区间与 break marker；图形不跨 break 连线。
- EMA/MACD 每个 calculation segment 独立绘制，预热区间显示 unavailable/warming，不补点。
- 历史信号和参考交易携带 owner segment、calculation segment、formula/reference version。
- 当前状态只来自截止时最新 calculation segment：1–33 根显示 `WARMING`，第 34 根显示
  `INDICATOR_READY_CROSS_UNEVALUABLE`，35 根及以上才显示 `CROSS_EVALUATED`；尾部未知缺口或 identity
  冲突则整体不可用。
- 页面必须把“部分可用窗口”与“完整窗口”分开。部分窗口不能显示为完整历史收益；统计注明覆盖区间、break
  数、预热区间和被排除区间。

## 5. 17 品种只读影响盘点

下表基于固定截止、当前 Catalog/MainContractMap、现有 Canonical 和已闭合来源证据。连续有效 Bar 数按最新
owner 物理合约从最近 break 后计数；35 是第一根可评价 exact CROSS 的门槛。结论均为**设计影响估算**。

| 品种 | 已确认异常合约（最后异常） | 固定窗口位置 | 截止日最新 owner | 最新 owner 最近 break / 连续有效 D1 | 设计影响估算 |
|---|---|---|---|---|---|
| BZ | BZ2610 (2026-03-20) | WARMUP_PREFIX | BZ2610 | 2026-03-20 / 125 | 潜在部分恢复 |
| C | C2609 (2026-09-10) | POST_OWNER_LIFECYCLE | C2611 | 无 / 207 | 潜在部分恢复 |
| EB | EB2606 (2025-09-19) | WARMUP_PREFIX | EB2610 | 2025-11-19 / 204 | 潜在部分恢复 |
| I | I2609 (2026-09-09) | POST_OWNER_LIFECYCLE | I2701 | 无 / 164 | 潜在部分恢复 |
| P | P2609 (2026-09-09) | POST_OWNER_LIFECYCLE | P2701 | 无 / 164 | 潜在部分恢复 |
| PG | PG2605 (2025-06-04) | WARMUP_PREFIX | PG2610 | 2025-12-09 / 190 | 潜在部分恢复 |
| Y | Y2609 (2026-09-09) | POST_OWNER_LIFECYCLE | Y2701 | 无 / 164 | 潜在部分恢复 |
| OI | OI2611 (2025-11-21) | WARMUP_PREFIX | OI2701 | 无 / 164 | 潜在部分恢复 |
| PF | PF2606 (2025-11-18)<br>PF2607 (2025-11-24)<br>PF2608 (2026-02-09)<br>PF2609 (2025-12-11)<br>PF2610 (2026-02-27)<br>PF2611 (2026-02-27) | WARMUP_PREFIX | PF2611 | 2026-02-27 / 140 | 潜在部分恢复 |
| PK | PK2611 (2025-12-19) | WARMUP_PREFIX | PK2611 | 2025-12-19 / 182 | 潜在部分恢复 |
| PL | PL2605 (2025-10-29)<br>PL2607 (2026-02-26)<br>PL2609 (2026-04-24)<br>PL2611 (2026-05-22) | WARMUP_PREFIX | PL2611 | 2026-05-22 / 84 | 潜在部分恢复 |
| PR | PR2605 (2025-09-16)<br>PR2606 (2025-11-18)<br>PR2607 (2026-02-11)<br>PR2609 (2026-04-07)<br>PR2610 (2026-02-09)<br>PR2611 (2026-03-11) | WARMUP_PREFIX | PR2611 | 2026-03-11 / 132 | 潜在部分恢复 |
| PX | PX2607 (2026-01-22)<br>PX2609 (2025-10-29)<br>PX2610 (2026-02-27)<br>PX2611 (2026-02-27) | WARMUP_PREFIX | PX2611 | 2026-02-27 / 140 | 潜在部分恢复 |
| RS | RS2609 (2026-09-09)<br>RS2611 (2026-08-20) | RANK1_OWNER_INTERVAL,WARMUP_PREFIX | RS2701 | 无 / 3 | 仍在预热 |
| SF | SF2605 (2025-05-20)<br>SF2607 (2025-12-19)<br>SF2611 (2025-12-24) | WARMUP_PREFIX | SF2611 | 2025-12-24 / 179 | 潜在部分恢复 |
| SH | SH2607 (2025-07-30)<br>SH2611 (2025-12-25) | WARMUP_PREFIX | SH2611 | 2025-12-25 / 178 | 潜在部分恢复 |
| SM | SM2607 (2025-12-25)<br>SM2611 (2026-04-15) | WARMUP_PREFIX | SM2611 | 2026-04-15 / 108 | 潜在部分恢复 |

EB2610、PG2610 的“最近 break”来自现有 Catalog `source_quality`，不是表中最初触发阻塞的合约。机器盘点
逐 owner 保留全部 break、未知端点和 first-evaluable 日期。

### 5.1 RS 必须单列

- RS2609 有 5 个 rank1 非正 Close 日，最后是 2026-09-09；该 owner 到 2026-09-11，只剩不足 35 根的
  重新预热空间。
- RS2611 的最后异常是 2026-08-20，属于成为 rank1 前的 warm-up prefix；其短 owner 区间同样不能把旧状态
  带入。
- 截止时 RS2701 物理生命周期只有 3 根有效 D1，因此即使新合同获批，当前状态仍是 warming，不能称 ready。

### 5.2 OI/PF 九月分区必须单列

OI2609/PF2609 九月 18 个独立端点已全部观察：8 个正 OHLC、10 个非正 Close。它们属于 66 个目标日的
子集，不是额外样本。现行分区合同下两个分区都不可发布。

方案 2 若获批，需要共享 Market Fact 层支持“Valid Bar + typed break”构成完整 expected endpoint union，
然后以新不可变 Parquet 和 Catalog pointer 发布。consumer 仍只能通过 MDS typed seam 读取，不能直接读
raw/staging。该发布是独立生产数据授权项；本提案和代码集成都不授权执行。

## 6. 版本和数据 Gate

需要新增并冻结：

- D1 quality classification policy version；
- quality endpoint union schema version；
- calculation segment identity version；
- `subing_reference_reverse_close_quality_segment_v2`；
- API response schema version及页面明确的 partial/warming/break 表达。

保持不变：

- `subing_ths_alert_15m_v1` Rule；
- `subing_ths_15m_v3` 及 15m Event exact identity；
- 30m/60m/1d 各自公式数学定义；
- Scope、通知、Runtime、auto_order=false；
- 旧 v1 reference 结果和身份。

数据 Gate 顺序：

1. owner 接受质量分类和参考统计合同；
2. fixture 中证明 endpoint union、break、35-bar 预热、batch/incremental/restart/prefix parity；
3. MDS opt-in reader 与普通 strict reader 回归；
4. 17 品种只读 dry-run，未知端点必须为 0，RS 仍 warming；
5. 独立 Review；
6. 单独申请精确 Canonical/Catalog 发布计划和生产写入授权；
7. 发布后按相同截止复验数据、D1 reference API、页面自然首屏；
8. develop 集成、release 和 Runtime 各自保持独立 Gate。

## 7. 实现工作拆分

1. **Market Fact 类型**：将现有 `PriceUnavailableFact` 扩成有界 union，保留旧分类读取；新增非正 Close
   类型及证据校验，未知类型拒绝。
2. **Canonical/Catalog**：验证每月 expected endpoint 等于 Bars 与 breaks 的互斥并集；提供不可变发布和
   strict readback，不允许 consumer glob 或 raw fallback。
3. **MDS**：新增 D1 opt-in quality endpoint API；普通 query 行为不变；通用变更增加其他 consumer 和退役
   品种保护测试。
4. **苏冰 reader**：只对 D1 历史参考采用新 seam；按 owner 和 break 构造 calculation segment，15m/30m/60m
   路径不变。
5. **Reference v2**：增加 `DATA_INTERRUPTED`、最后有效标记、holding bars 和独立统计；无 synthetic exit。
6. **API/Web**：返回 coverage intervals、break、warming、partial；K 线和指标断线，当前状态不由旧段推导。
7. **证据**：17 品种固定截止矩阵、RS warming、OI/PF mixed partition、旧 15m Rule/Event/公式身份不变。

## 8. 验收条件

- 任一 expected endpoint 精确属于 Valid Bar 或一个已证实 break；重复、缺失、额外、未知均 fail closed。
- 全零不变成 `NO_TRADE`，正 Close/零 OHL 不因公式只看 Close 被放宽。
- break 前后指标、CROSS previous-state、交易和 segment identity 均不继承。
- 第 1–33 根 `WARMING`、第 34 根 `INDICATOR_READY_CROSS_UNEVALUABLE`、第 35 根起
  `CROSS_EVALUATED` 的边界由纯 Kernel fixture 和实际 Calendar 端点共同证明。
- calculation segment id 明确绑定 `1d`、物理合约、权威 owner 起点、前置 break boundary、首根有效 Bar 和
  质量策略版本；owner 终点、未来追加映射或全局变化 revision 不得改写历史身份。
- batch、incremental、restart、prefix 结果一致；同输入 hash 结果确定。
- 质量中断与 rollover 中断可区分，无虚构退出价、收益或当前浮动。
- 15m Rule、Scope、Event、通知、Runtime 以及 15m/30m/60m 历史 reference 回归完全不变。
- 17 项只读影响结果只能称 `DESIGN_IMPACT_ESTIMATE`；在生产数据发布、同截止 API 与页面验收前，
  `223/240` 和 17 blocked 不变。

## 9. 当前 Gate

候选实现、生产应用和固定截止 240 组合数据/API/页面验收均已完成；精确回执与读回见
`outputs/subing-four-period-readiness-20260918/`。该结果允许进入 develop 集成，但不授权 main/tag/release、
Runtime promotion、Scope/通知修改或自然业务验收。
