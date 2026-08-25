# HTDY 全周期 × Active60 统一观察与 Alert 设计

状态：Proposed  
日期：2026-08-25  
设计基线：`develop@48d8bd512dc50b5e87bf524aed5edb448d85a5b1`  
任务等级：Lane 3（指标可信口径 + Alert Runtime + migration）

## 1. 背景与当前事实

当前火天大有（HTDY original）已经具备以下基础能力：

- Python Indicator Kernel `huotian_dayou_original_v0` 的 `supported_intervals` 已是正式七周期：`1m / 5m / 15m / 30m / 60m / 1d / 1w`；
- Web 侧 HTDY observation 按传入 Bar 计算，本身没有 15m 专用公式；
- 当前 Web Overlay capability 却把 HTDY 限定为 `15m`，因此用户切换其他周期后会进入 unsupported 状态并停止绘制；
- 当前 Alert Rule `htdy_original_15m`、HTDY evaluator、Alert Runtime message parser、event-cutoff read window、通知文案均显式写死 15m；
- Market Live 当前发布 completed `1m`，并由 1m 派生并发布 `5m / 15m / 30m / 60m`；`1d / 1w` 不属于 Live Pub/Sub 派生面，而是在盘后 Canonical 维护中形成正式数据；
- 当前 Alert Rule Scope 只保存 `scope_products`，因此只能表达“某个品种开/关”，不能表达“某个品种的某个周期开/关”；
- 当前 `alert_events` 的唯一键为 `(rule_id, symbol, bar_end)`；Alert V2 曾有意从含 frequency 的 V1 identity 收敛为该 identity，以保证 SuBing 同一 Rule + 品种 + bar_end 只能形成一个正式信号；
- HTDY 全周期后，同一品种、同一 `bar_end` 可以合法出现多个 frequency 的 observation，因此存储层必须允许 HTDY 跨周期共存，同时不能破坏 SuBing 现有 bar-level 幂等语义；
- 当前 `operational_products.txt` 与 active universe 一致，共 60 个品种。产品覆盖继续由该文件驱动，不在 HTDY 代码中硬编码“60”或具体品种列表。

本设计是新的 HTDY 单系统全周期方向，不恢复已经撤回的“四系统 Active60 全周期观察”方向。

## 2. 修订后的目标

本次目标固定为：

> HTDY 在当前 operational universe 的全部品种、全部正式周期上统一具备“图表观察 + Alert 资格”；Web 上的 HTDY 开关只控制**当前品种 × 当前图表周期**这一对 Alert Scope。

具体结果：

1. 用户选择“火天大有”后，可以在 `1m / 5m / 15m / 30m / 60m / 1d / 1w` 任意切换，Overlay 始终正常计算和显示，不再出现“当前周期不支持该 Overlay”。
2. 当前 60 个 operational products 全部具有 HTDY 七周期 capability，不再存在 JM/15m 这种能力限定。
3. Web 仍然只显示一个 HTDY 开关，但这个开关的状态随当前 `symbol + frequency` 变化：
   - 当前是 `JM + 15m`，开关只读写 `JM + 15m`；
   - 切换到 `JM + 5m`，开关只读写 `JM + 5m`；
   - 切换到 `RB + 15m`，开关只读写 `RB + 15m`。
4. 打开一个周期不能自动打开同品种的其他周期；关闭一个周期也不能关闭同品种其他已开启周期。
5. 不增加七个并排的周期开关，不增加第二套 HTDY Rule，不拆分“观察版”和“预警版”。
6. D1/W1 仍然在盘后 Canonical 更新完成后检查并提醒。
7. 同一时间不同周期的 HTDY 如果分别触发，分别形成 AlertEvent 并分别推送，不做跨周期合并。
8. HTDY original 仍是已知 future-looking / repainting 的 observation-only 指标；本次只扩大观察与提醒 capability，不把它升级为正式回测、正式策略、交易信号或订单能力。

## 3. 非目标

本次明确不做：

- 不做七个固定开关同时展示；
- 不做“全周期一键开启”；
- 不自动把 60 个品种或七个周期全部打开提醒；
- 不把切换图表周期本身当作 Scope mutation；
- 不做消息合并、节流、队列、retry、replay、backfill、outbox 或 fallback；
- 不新增 HTDY 派生表、第二套事件表、第二套 scheduler；
- 不修改 HTDY original 数学公式、XMA 语义、25 周期参数、3 连续 K 线观察判定；
- 不把 `continuous` 或指定 `contract` 变成 Alert 身份；Alert 继续是 `actual_dominant` 当前 rank1 观察；
- 不改变 SuBing Alert 的 5m/15m 触发、现有品种级 Scope、同 boundary 抑制和 bar-level 正式 Event 幂等语义；
- 不做自动交易，`auto_order=false` 保持不变。

## 4. 统一 Capability Contract

### 4.1 周期集合

HTDY 的唯一正式周期集合固定为：

```text
1m | 5m | 15m | 30m | 60m | 1d | 1w
```

Web Overlay 与 HTDY Alert Rule 必须对这七个周期保持一致，不再分别维护“Web 支持周期”和“Alert 支持周期”两套 capability 口径。

注意：

```text
capability supported
!=
alert enabled
```

七周期都“可以”观察和预警，但是否真正创建 AlertEvent，由当前 `symbol × frequency` Scope 决定。

### 4.2 品种集合

HTDY 不持有自己的品种名单。能力范围始终为：

```text
load_operational_products()
```

当前验收基线应读出 60 个品种；未来 `operational_products.txt` 合法变化时，HTDY 自动继承新的 operational universe，不要求同步修改 HTDY 常量。

新增 operational product 只获得 capability，默认没有任何 HTDY frequency Scope 被开启。

### 4.3 图表序列与 Alert 序列

图表保持现有三种展示序列：

```text
continuous | actual_dominant | contract
```

三种序列均可在七周期显示 HTDY Overlay。

Alert 继续固定为：

```text
series_kind = actual_dominant
main_contract_rank = 1
```

Web 开关的 identity 是：

```text
rule_code + symbol + frequency
```

而不是：

```text
rule_code + series_kind + contract + symbol + frequency
```

原因是用户是在“品种 × 周期”维度决定是否提醒；图表当前选择 continuous、actual_dominant 或具体 contract 只影响观察视图，不能让 Alert Scope 跟随图表序列漂移。

因此，“图表观察和 Alert 不拆开”在本设计中精确定义为：**同一个 HTDY original、同一个七周期 capability、同一条 Alert Rule；是否提醒再由当前品种 × 当前周期开关控制。**

## 5. Web 设计

### 5.1 HTDY Overlay

`RESEARCH_OVERLAY_DEFINITIONS.htdy.supportedFrequencies` 改为全部正式 Market frequencies。

结果：

- 选择 HTDY 后切换任一正式周期，`researchOverlayCapability()` 都应返回 supported；
- `visibleMainIndicatorsForOverlay('htdy', ...)` 始终保留 `htdy`；
- 当前“当前序列或周期不支持该 Overlay”提示不应因 HTDY + 合法周期出现；
- optional EMA 行为保持现状；
- HTDY 的 repaint 风险提示、unstable tail 27 bars、observation-only 文案保持。

不新增新的 Overlay id，也不新增 HTDY 参数设置。

### 5.2 HTDY 当前品种 × 当前周期开关

继续复用当前 `ProductAlertRules` 区域中的单个 HTDY `NSwitch`，但组件必须接收当前 Market `frequency`。

开关语义：

```text
当前图表 = JM + 15m
HTDY switch ON
-> 只开启 JM + 15m

切换图表 = JM + 5m
-> 不执行任何 Scope 写入
-> 开关显示 JM + 5m 的独立状态

JM + 5m switch ON
-> 只新增 JM + 5m
-> JM + 15m 保持原状态

JM + 5m switch OFF
-> 只移除 JM + 5m
-> JM + 15m 保持原状态
```

推荐显示标签：

```text
火天大有 · 15m
火天大有 · 5m
火天大有 · 1d
```

标签跟随当前图表周期更新。不得显示“火天大有 · 全周期”，因为开关不代表全周期。

### 5.3 频率切换必须是纯读状态切换

切换当前 Market frequency：

- 允许重新计算开关显示状态；
- 不允许自动 PUT Scope；
- 不允许把上一个周期的 ON 状态复制到新周期；
- 不允许因为 Overlay 被选中而自动启用当前 frequency；
- 不允许因为 Overlay 被取消而自动关闭 Alert。

也就是说：

```text
选择 Overlay = 图表行为
点击 Alert Switch = Scope mutation
```

二者仍然独立。

### 5.4 Product Alert State 返回当前品种的 enabled frequencies

现有 `ProductAlertRuleState` 只有 `enabled_for_product`，无法让 Web 在切频时准确判断 HTDY 当前周期状态。

修订后的 read model 增加：

```text
enabled_frequencies: list[MarketFrequency]
```

HTDY：

- 返回当前 symbol 已开启的全部 HTDY frequencies；
- Web 用 `enabled_frequencies.includes(currentFrequency)` 计算 HTDY switch；
- 切频时直接使用同一份读模型更新 switch，不因为切频执行 Scope mutation。

现有 `enabled_for_product` **保留为派生摘要字段**，定义为“该品种至少有一个 frequency 已开启”，用于保持当前产品状态读模型兼容；HTDY Web Switch **不得**再用它作为 value。

SuBing 的现有品种级 Scope 不改；它的 UI 行为和 mutation 语义继续按当前产品合同执行。

### 5.5 持久 Alert Marker

HTDY persistent Alert marker 支持周期同步扩大到七周期。

同一 AlertEvent 只显示在与 `event.frequency` 相同的图表周期：

- 15m Event 只显示在 15m；
- 60m Event 只显示在 60m；
- 不跨周期复制 marker。

Marker 是否存在由历史 AlertEvent 决定，不取决于当前 Switch 此刻是否仍为 ON。

## 6. HTDY Scope 持久化设计

### 6.1 当前模型为什么不够

当前 `AlertRule` 只有：

```text
scope_products: ["jm", "rb", ...]
```

它只能表达：

```text
JM = ON/OFF
```

不能表达：

```text
JM 15m = ON
JM 5m  = OFF
JM 60m = ON
```

因此本次不能只在前端记录当前 frequency，否则 Runtime 仍会把整个品种视为开启，形成错误通知。

### 6.2 推荐方案：AlertRule 增加 HTDY frequency-scope JSON

在现有 `alert_rules` 表新增一个轻量字段：

```text
scope_product_frequencies
```

逻辑结构：

```json
{
  "jm": ["15m", "60m"],
  "rb": ["5m"],
  "ag": ["1d", "1w"]
}
```

规范：

- symbol 使用 normalized lower-case operational symbol；
- frequency 必须属于该 Rule 的 `input_frequencies`；
- frequency 按正式固定顺序去重存储；
- 没有任何 frequency 的 symbol 不保留空数组 key；
- 未知 symbol/frequency fail-closed；
- 更新仍使用现有 Rule row `FOR UPDATE`，修改后整体替换 normalized JSON，保持单用户简单写模型。

本字段只表达 Scope，不复制 Rule capability；Rule capability 仍来自 Code Registry。

### 6.3 两条现有 Rule 的 Scope 权威边界

为了不扩大 SuBing 任务范围，Scope authority 按现有 Rule kind 保持窄分工：

**HTDY / `INDICATOR_OBSERVATION`**

```text
scope_product_frequencies = authority
scope_products             = 必须为空
```

**SuBing / `FORMAL_SIGNAL`**

```text
scope_products             = authority（保持现状）
scope_product_frequencies  = 必须为空
```

Service/Runtime 每次读取 Scope 时必须验证该互斥关系：

- HTDY 如果同时出现非空 `scope_products`，fail-closed 为 Scope state invalid；
- SuBing 如果出现非空 `scope_product_frequencies`，fail-closed 为 Scope state invalid；
- 不允许把两个字段 union 后继续运行，因为那会制造双事实源。

不新增通用 Scope DSL，不新增第三张 Scope 表，不把两个固定 Rule 强行抽象成复杂框架。

### 6.4 为什么不新建 alert_rule_scopes 表

对当前只有两个固定 Rule 的本地单用户项目，新建：

```text
alert_rule_scopes(rule_id, symbol, frequency, ...)
```

虽然关系模型更规范，但会新增第三张 Alert 表、额外 ORM、join、migration 和清理语义。本次只需要为 HTDY 保存一个很小的 `symbol -> frequencies` map，JSON 更符合当前个人项目的复杂度边界。

如果未来出现多个 frequency-scoped Rule，再根据真实重复决定是否抽表；本次不预建设。

### 6.5 为什么不把 pair 塞进 scope_products

拒绝把 pair 编码成：

```text
jm@15m
```

因为这会污染现有 `scope_products` 的合法 symbol 语义，破坏 normalize/operational validation/heartbeat 等现有代码，且可读性差。

## 7. Scope API 设计

### 7.1 Read API

现有：

```text
GET /api/alerts/products/{symbol}
```

继续保留，HTDY state 增加 `enabled_frequencies`。

示例：

```json
{
  "rule_code": "htdy_original_15m",
  "input_frequencies": ["1m", "5m", "15m", "30m", "60m", "1d", "1w"],
  "enabled_for_product": true,
  "enabled_frequencies": ["15m", "60m"]
}
```

其中 `enabled_for_product=true` 只表示至少一个周期开启；HTDY Web Switch 的当前值必须使用 `enabled_frequencies`。

### 7.2 HTDY frequency mutation API

新增明确的 pair-level mutation：

```text
PUT /api/alerts/rules/{rule_code}/scope/{symbol}/{frequency}
body = { "enabled": true|false }
```

只允许 frequency-scoped HTDY Rule 使用。

语义：

```text
ON  -> 将 frequency 加入该 symbol 的 enabled set
OFF -> 只移除该 frequency
```

现有 product-level endpoint：

```text
PUT /api/alerts/rules/{rule_code}/scope/{symbol}
```

继续服务 SuBing 的现有品种级 Scope，不把 SuBing 偷换成当前周期 Scope。

这样避免一个 endpoint 通过 nullable frequency 隐式拥有两套容易误用的语义。

### 7.3 Scope mutation 幂等

- 已开启的 pair 再 ON：返回当前状态，不产生额外副作用；
- 未开启的 pair 再 OFF：返回当前状态；
- 开/关一个 pair 不触碰其他 frequency；
- 非 operational symbol、非正式 frequency、非 HTDY Rule 访问 pair endpoint 都 fail-closed；
- Scope mutation 不发送通知，不补发历史 Event。

## 8. Alert Rule 设计

### 8.1 保留单一 HTDY Rule

仍然只有一条 HTDY Rule，不按周期拆成七条。

本次保留数据库稳定标识：

```text
rule_code = htdy_original_15m
```

虽然名称包含历史 `15m` 后缀，但它已经是 production 持久身份，并被已有 `alert_rules / alert_events / Web` 引用。为避免把能力扩展、Scope migration 与 Rule rename 绑在一次 production migration，本次不改 rule_code。

代码必须注释清楚：该字符串是 legacy stable identity，当前 capability 不再由名称中的 `15m` 推导。

`HTDY_RULE.input_frequencies` 改为正式七周期。

### 8.2 Runtime Scope 判定

HTDY 每个 Event 的资格必须同时满足：

```text
rule enabled
AND symbol in operational universe
AND event_frequency in HTDY input_frequencies
AND scope_product_frequencies[symbol] contains event_frequency
```

只满足“这个品种有其他周期开启”不够。

例如：

```text
JM enabled_frequencies = [15m]
收到 JM 5m completed bar
-> 不评估 HTDY
-> 不创建 Event
-> 不发送通知
```

这条必须由 Runtime focused tests 锁定。

### 8.3 Heartbeat 不扩 schema

现有 Alert heartbeat 的 `scope_product_count` 继续表示：

> 当前至少有一个 Alert Scope 的 distinct operational product 数量。

HTDY 一个品种开多个 frequency 仍只计一个 product。第一版不为 pair 数量新增 Redis schema 字段，避免为了可观察性扩大 Runtime status 合同。

## 9. AlertEvent 身份与幂等设计

### 9.1 HTDY 为什么需要 frequency 进入 Event identity

七周期后，同一品种可以在同一 `bar_end` 同时出现多个合法 HTDY Event：

```text
10:00
-> 5m close
-> 15m close
-> 30m close
-> 60m close
```

当前数据库唯一键：

```text
(rule_id, symbol, bar_end)
```

会错误地把 HTDY 不同周期 observation 视为同一个 Event。

### 9.2 不能同步放宽 SuBing business identity

Alert V2 当前把 SuBing formal signal 的同一 `rule + symbol + bar_end` 视为一个业务事件，`frequency` 是该事件结果属性之一。现有 Service 回归要求同一 bar-level identity 只改变 frequency 时 fail-closed。

因此本次不能为了 HTDY 改掉 SuBing 的正式信号幂等语义。

### 9.3 数据库存储唯一键

数据库通用 storage constraint 改为：

```text
(rule_id, symbol, frequency, bar_end)
```

需要 migration：

1. 删除 `uq_alert_events_rule_symbol_bar_end`；
2. 创建 `uq_alert_events_rule_symbol_frequency_bar_end`；
3. ORM `UniqueConstraint` 同步。

已有 Event 数据天然满足新的 storage key，不需要回写 Event 内容或 backfill。

### 9.4 Rule-kind-specific business identity

`AlertService.create_event()` 按 `AlertRuleKind` 保持不同业务幂等。

**HTDY / `INDICATOR_OBSERVATION`**

```text
business identity = (rule_id, symbol, frequency, bar_end)
```

- 同 frequency 重复：idempotent，返回 None，不重发；
- 同 bar_end 不同 frequency：允许分别创建 Event。

**SuBing / `FORMAL_SIGNAL`**

```text
business identity = (rule_id, symbol, bar_end)
```

- 完全相同 Event：idempotent；
- 同 bar_end 但 frequency、contract、trading_day、result_codes 或 lower_tf_confirmation 任一变化：继续 `ALERT_EVENT_CONSISTENCY_ERROR`；
- 不允许数据库 constraint 变宽后出现第二条跨周期 SuBing Event。

实现阶段 FORMAL_SIGNAL 创建前必须先按 bar-level identity 查询并执行现有 consistency check。

当前 Event 只有 Alert Runtime 内部单写入口，本版不为这个窄模型新增通用 identity framework。如果实现 Review 发现已经存在第二个并发 Event writer，必须停回设计 Gate。

## 10. HTDY Evaluator 设计

把 `HtdyOriginal15mEvaluator` 收敛为一个可处理七周期的 HTDY original evaluator，但仍然只处理单个 completed event bar。

固定合同：

```text
indicator      = huotian_dayou_original_v0
series_kind    = actual_dominant
frequency      = 当前 event frequency，必须属于七周期 allowlist
context_bars   = 32
cutoff         = 当前 completed event bar_end
result         = 只读取计算结果最后一根 buy/sell observation
auto_order     = false
```

32 bars 不随周期改变；算法仍按“Bar 数”而不是自然时间长度计算。

Evaluator 不扫描 repaint 区域找旧信号，不撤销旧 AlertEvent，不把未来重新计算后的历史形态当成新 Event。

### 10.1 冻结旧 realtime policy validator 不修改

`realtime_observation_policy.py` 中 JM/15m 的旧 `RealtimeRepaintingObservationPolicy` / `ClosedBarRealtimeObservationPolicy` 是冻结兼容资产，当前 Alert V2 evaluator 并不以它作为 active capability gate。

本任务不把该冻结对象扩成 Active60/七周期，也不修改其 exact-identity/hash 测试；新的 active HTDY Alert capability 由 Indicator Registry + Formal Policy scoped consumer + Alert Rule/evaluator/Scope 合同表达。

## 11. Runtime 触发设计

七周期的数据到达方式不同，但对外仍是同一条 HTDY Rule；每次评估前都必须检查当前 `symbol × frequency` Scope。

### 11.1 日内五周期：Live completed-bar trigger

以下周期直接使用现有：

```text
live:bar:{symbol}:{frequency}
```

周期：

```text
1m | 5m | 15m | 30m | 60m
```

改动：

- Alert message parser 接受上述五个日内周期；
- Rule definition frequency filter 决定该 Rule 是否支持；
- HTDY Scope 再精确检查该 symbol + event_frequency 是否 ON；
- SuBing 仍只接受 5m/15m，Scope 与同 boundary 抑制规则保持不变；
- HTDY `_evaluate_htdy()` 使用 event_frequency，而不是固定 M15；
- `_window_matches_event` 使用请求 frequency，而不是固定 `15m`。

Market Live 已经从 completed 1m 形成 5m/15m/30m/60m，不新增第二个聚合器。

### 11.2 D1 / W1：Canonical-updated trigger

保留已批准方向：D1/W1 不进入 Live derive。

复用现有盘后 Canonical 更新完成后的 `market:state` seam，发布明确 reason：

```json
{
  "trading_day": "YYYY-MM-DD",
  "reason": "canonical_updated"
}
```

Alert Runtime 只有收到 `reason=canonical_updated` 才检查 D1/W1；普通 Market state 变化不触发。

盘后流程：

```text
HistoricalDataManager.update passed/noop
-> Canonical 已处于可读状态
-> market:state(reason=canonical_updated, trading_day=T)
-> Alert Runtime 读取 enabled HTDY frequency scopes
-> 只选择 D1 已开启的 symbol 检查 D1
-> 只选择 W1 已开启的 symbol 检查 W1
-> latest bar.trading_day 必须 == T
-> current-bar evaluator
-> AlertEvent
-> one-shot PushPlus
```

若某品种只开启 1d，没有开启 1w：

```text
盘后只检查 D1
不检查 W1
```

`W1` 继续完全复用 `MarketDataService` 已有“完整交易周 + weekly owner”规则，不在 Alert 内复制周线主力归属算法。

### 11.3 No-backfill 保持

`latest bar.trading_day == T` 是 no-backfill 边界：

- 周一到周四如果最新 W1 仍属于上周，不补发；
- 节假日缩短周只认 MarketDataService/TradingCalendar 的正式完整周事实；
- Alert Runtime 如果在周线形成当天宕机并错过 canonical_updated，不在下一交易日补发；
- 重复收到同一 canonical_updated 只依靠 Event 幂等，不产生重复通知。

D1/W1 的用户可见提醒时机为**盘后 Canonical 更新完成后**，不是 Session 最后一根 1m 到达瞬间。

### 11.4 不把 D1/W1 放进 Live derive

拒绝在 Live 侧从 1m 再造 D1/W1，因为：

- 正式 D1 来自交易所日行情；
- W1 来自完整同源 D1；
- Live 聚合会产生第二套日/周事实；
- 夜盘、节假日、完整交易周、跨主力 owner 都会被重复实现。

## 12. Market event-cutoff read 设计

当前 `MarketReadService.bars_until()` 只允许 `actual_dominant + 15m`，必须泛化为 HTDY 七周期 event-cutoff reader，但继续 fail-closed。

### 12.1 日内

`1m/5m/15m/30m/60m`：

- 读取 Canonical historical page；
- 合并当前交易日 Live Redis 同周期 bar；
- 精确截断到 event `bar_end`；
- 必须存在 exact cutoff bar；
- current rank1 contract 仍从当天 immutable Live subscription snapshot 唯一解析；
- 不跨频回退，不自己重新聚合。

### 12.2 D1/W1

`1d/1w`：

- 只读 Canonical `actual_dominant`；
- 不依赖可能已经 cleanup 的 Live subscription；
- contract identity 从 `MarketDataService` 返回的 `resolved_contract_segments` 唯一解析；
- exact cutoff bar、trading_day、segment owner 任一不唯一时 fail-closed；
- W1 owner 只认 MarketDataService 已实现的完整交易周解析。

### 12.3 不可用输入

少于 32 根、exact cutoff 缺失、主力身份不唯一、Canonical/Live 读取失败时：

- 不创建 Event；
- 不发送通知；
- 不使用其他周期替代；
- 不补零、不猜合约；
- 沿用现有 Rule 故障隔离与公开 processing failure 观察，不新增 unavailable 状态表。

## 13. Notification 设计

HTDY 继续发到既有 `htdy_observers` Topic，每 Event 最多一次 provider request。

修改 `_format_htdy_message()`：

- 接受七周期；
- 使用 `message.frequency` 动态显示实际周期；
- 继续显示品种、主力合约、收线时间和“研究观察，非交易指令”；
- provider accepted 仍不等于微信送达。

同一时刻多个已开启周期分别触发时，分别发送。例如：

```text
JM 15m = ON
JM 60m = ON
10:00 两周期均触发
-> 15m Event + 一次通知
-> 60m Event + 一次通知
```

如果 JM 30m = OFF，即使 10:00 的 30m 也满足 HTDY 数学条件，也不创建 30m Event、不通知。

本次不做跨周期合并，因为合并会引入等待窗口、缓存和新的通知时序规则。

## 14. HTDY original 重绘语义保持不变

扩大周期范围不能掩盖 original 的既有风险：

- symmetric XMA 仍有 future dependency；
- current last bar 使用当时可见的 clipped window；
- 后续新 Bar 到达后，历史 HTDY 可能重绘；
- AlertEvent 表示“当时该 completed bar 首次观察到的事实”，一旦创建保持 immutable；
- 不因为后续重绘撤回 Event，也不发送撤回提醒；
- Web 历史图可按当前完整窗口重新计算，因此历史图形与当时 AlertEvent 可能不同；Alert marker 继续作为当时事实保留。

这仍然不是正式策略有效性、回测或交易证据。

## 15. Migration 与兼容性

本任务需要一个 Alert Application Domain migration。

### 15.1 Schema 变更

允许：

1. `alert_rules` 增加 `scope_product_frequencies` JSON 字段，默认空对象；
2. `alert_events` unique constraint 改为 `(rule_id, symbol, frequency, bar_end)`；
3. ORM 与 schema/read model 同步；
4. Service 增加 HTDY pair-scope mutation/read；
5. SuBing 保持现有 product-level Scope 与 bar-level Event identity。

不新增表。

### 15.2 现有 HTDY Scope 的迁移规则

这是本次修订最重要的兼容语义。

当前 production/develop 的 HTDY `scope_products` 都是在“HTDY 只支持 15m”合同下产生的，因此 migration 必须解释为：

```text
原 scope_products = [jm, rb]

迁移后：
scope_product_frequencies = {
  "jm": ["15m"],
  "rb": ["15m"]
}
scope_products = []
```

即：

> **现有已开启品种只继承 15m ON，不自动开启其他六个周期。**

这样 migration 不会因为“代码支持七周期”而扩大真实通知 Scope。

SuBing 的 `scope_products` 原样保留，`scope_product_frequencies` 保持空对象。

### 15.3 禁止的 migration 行为

- 不把当前 HTDY scope 自动扩成七周期；
- 不新增任何当前未开启品种；
- 不修改历史 AlertEvent 内容；
- 不删除历史 Event；
- 不把 SuBing scope 迁成 frequency scope；
- production migration 未经独立明确执行意图不得运行。

## 16. 预计实现范围

实现阶段预计只触及现有模块，不创建新子系统：

```text
Web
- apps/quant-web/src/pages/market/chart.vue
- apps/quant-web/src/components/market/ProductAlertRules.vue
- apps/quant-web/src/composables/useProductAlertScope.ts
- apps/quant-web/src/api/alerts.ts
- apps/quant-web/src/utils/mainIndicators.ts
- apps/quant-web/src/utils/alertRules.ts
- apps/quant-web/src/utils/alertMarkers.ts
- 对应 unit / e2e tests

Alert API / Domain
- services/quant-api/app/api/alerts.py
- services/quant-api/app/schemas/alerts.py
- services/quant-api/app/alerts/registry.py
- services/quant-api/app/alerts/evaluators.py
- services/quant-api/app/alerts/runtime.py
- services/quant-api/app/alerts/composition.py
- services/quant-api/app/alerts/service.py
- services/quant-api/app/alerts/models.py
- services/quant-api/app/alerts/notification.py

Market read / trigger seam
- services/quant-api/app/market_data/market_read_service.py
- services/quant-api/app/market_data/after_market.py

Migration
- 新 Alembic revision（接在当前 head 后）

Canonical docs
- docs/INDICATOR_KERNEL.md
- PROJECT_SOURCE.md
- AGENTS.md
- docs/DEVELOPMENT.md
- DECISIONS.md
- STATUS.md（只有实现/验证/集成真实发生后才更新）
```

如果实现过程中发现必须新增 scheduler、queue、第二套 daily/weekly aggregation、新 Application Domain、第三张 Scope 表或通用 Event identity framework，应停止并回到设计 Gate，不得静默扩范围。

## 17. 验收标准

### 17.1 Web Overlay

1. 当前 operational 60 中任一品种选择 HTDY 后，七个正式周期都能显示 HTDY，且不出现 HTDY unsupported warning。
2. HTDY Overlay 在 `continuous / actual_dominant / contract` 三种现有图表序列均保持可用。
3. HTDY risk/repaint 提示保持现状。

### 17.2 当前品种 × 当前周期 Switch

1. Web 只显示一个 HTDY Switch，不展示七个并排开关。
2. Switch 标签显示当前图表 frequency。
3. `JM 15m` ON 后切换 `JM 5m`，5m 如果未开启必须显示 OFF。
4. 打开 `JM 5m` 后，`JM 15m` 仍保持 ON。
5. 关闭 `JM 5m` 后，`JM 15m` 仍保持 ON。
6. 切换 frequency 本身不调用 Scope mutation API。
7. 切换 symbol 后展示该 symbol 自己的 enabled frequency set。
8. Overlay 选择/取消不修改任何 Alert Scope。

### 17.3 Scope Backend

1. HTDY Scope identity 精确为 `rule + symbol + frequency`。
2. HTDY pair endpoint 只允许七个正式 frequency 和 operational symbol。
3. 同 pair 重复 ON/OFF 幂等。
4. 一个 pair mutation 不改变同 symbol 其他 frequencies。
5. HTDY Runtime 只有当前 event 的 exact pair ON 才评估。
6. HTDY `scope_products` 与 SuBing `scope_product_frequencies` 任一出现非空混用都 fail-closed。
7. SuBing 继续使用现有 `scope_products`，不因本任务变成 frequency scope。
8. heartbeat `scope_product_count` 继续按 distinct products 统计，不增加 Redis schema。

### 17.4 Runtime / Alert

1. HTDY Rule capability 精确等于七个正式周期。
2. HTDY evaluator 七周期复用同一 original Kernel、同一 32-bar current-event cutoff 语义。
3. Alert Runtime 接受 completed `1m/5m/15m/30m/60m` live bar；SuBing 仍只消费 5m/15m。
4. 对任一 live event，HTDY Scope 必须按 event_frequency 精确匹配。
5. `market:state` 只有 `reason=canonical_updated` 才能触发 D1/W1。
6. D1/W1 只检查相应 frequency ON 的 products。
7. D1/W1 latest canonical bar 的 `trading_day` 必须等于本次 canonical-updated trading day，禁止补发旧日/旧周。
8. HTDY 同一 rule + symbol + bar_end 的不同 frequency 可以各自创建 Event；同 frequency 重复输入仍幂等且不重发。
9. SuBing 同一 rule + symbol + bar_end 仍只能形成一个 formal Event；只改变 frequency 仍必须 `ALERT_EVENT_CONSISTENCY_ERROR`。
10. 通知文案动态显示实际 frequency；topic audience、one-shot、provider acceptance 语义不变。
11. 无 replay/backfill/retry/outbox/queue/fallback/order。

### 17.5 数据与因果

1. 日内只消费同周期 completed Bar，不跨频回退。
2. D1/W1 只消费正式 Canonical；W1 owner 由 MarketDataService 唯一解析。
3. exact cutoff、rank1 identity、coverage 或 32-bar context 不完整时不产生 Event/通知。
4. original future-looking/repainting metadata、24-bar future dependency、27-bar Web repaint scan zone 保持不变。
5. 冻结的 JM/15m legacy realtime observation policy/hash 测试保持不变，不被冒充为新 Active60 capability。
6. `auto_order=false`。

### 17.6 Migration

1. `alert_rules.scope_product_frequencies` 存在且默认空对象。
2. 现有 HTDY `scope_products` 每个 symbol 只迁移为 `15m` ON。
3. migration 后 HTDY `scope_products` 必须为空，不产生双事实源。
4. SuBing `scope_products` 原样保持，`scope_product_frequencies` 必须为空。
5. migration 不自动增加任何品种或 frequency。
6. PostgreSQL AlertEvent storage constraint 为 `(rule_id, symbol, frequency, bar_end)`。
7. migration 前已有 Event 数量和内容保持不变。
8. isolated PostgreSQL migration test 必须覆盖 Scope 数据转换和新 Event unique key。
9. Service regression 必须证明 storage constraint 变宽后 SuBing bar-level identity 仍未改变。

## 18. 验证要求

这是 Lane 3 变更，不能只跑前端测试。

实现阶段至少需要：

- HTDY Kernel / policy focused tests；
- Alert registry / scope service / evaluator / runtime / notification focused tests；
- Alert API/schema tests，覆盖 pair read/write；
- MarketReadService / Live Market / after-market focused tests；
- Alembic migration tests，使用隔离 PostgreSQL；
- Web mainIndicators / alertRules / alertMarkers / ProductAlertRules / scope composable unit tests；
- Web Playwright 覆盖 HTDY 七周期切换 + 当前 pair Switch 行为；
- full non-isolated backend suite；
- Ruff；
- Mypy；
- Web full unit；
- Web production build；
- full Playwright；
- OpenSpec validate；
- secret scan；
- diff / canonical consistency checks。

代码完成后还应做一次**只读** Active60 × 七周期 capability matrix 验证：确认每个 operational product 的每个正式 frequency 都能进入合法图表/评估入口；Scope ON/OFF 另以测试和只读状态验证，不自动改真实 Scope。

该矩阵只证明 capability coverage，不证明策略有效、盈利或可交易。

真实通知 canary、production migration、Scope mutation、release/tag、Runtime switch/promotion 都是独立外部 Gate，本 Spec 与自动化测试不授权执行。

## 19. 发布与 Runtime Gate

建议流转：

```text
Spec approved
-> Lane 3 implementation
-> focused + full verification
-> independent Review
-> develop integration
-> release candidate
-> 用户批准 production migration / release（各自按正式流程取得明确意图）
-> 用户批准 Runtime promotion
-> 只读核对迁移后 HTDY symbol × frequency Scope
-> 启动新 Runtime
-> 自然事件观察
```

与上一版 Spec 不同，本版 migration **不会**让当前已开启的 HTDY 品种从 15m 自动扩大到七周期，而是只保留其原有 15m 开启事实。

用户后续需要哪个品种的哪个 frequency，就在该品种该周期页面上手工打开。

release 批准、production migration 与 Runtime promotion 不能由本 Spec、代码合入或测试结果互相推导。

## 20. 方案比较与取舍

### 方案 A：单 HTDY Rule + 当前 symbol × frequency Switch + JSON frequency scope（推荐）

- Web/Alert capability 都支持七周期；
- 一个 HTDY Rule；
- Web 始终只显示一个跟随当前 frequency 的 Switch；
- Scope 精确保存 `symbol -> enabled frequencies`；
- 日内使用现有 Live bar；
- D1/W1 使用现有盘后 Canonical-updated seam；
- 不新增 Scope 表或 scheduler。

优点：精确满足用户的操作习惯，同时保持个人项目结构简单。  
缺点：AlertRule 对 HTDY 与 SuBing 使用两种窄 Scope authority，需要 Service 按现有 Rule kind 显式处理。

### 方案 B：新建 `alert_rule_scopes` 表

暂不采用。模型更规范，但当前只有一个 frequency-scoped Rule，会增加第三张 Alert 表和额外 ORM/join/migration 复杂度。等真实出现第二个 frequency-scoped Rule 再评估抽表。

### 方案 C：七周期拆成七条 HTDY Rule

拒绝。会造成七条 Rule、更多数据库 row 和 Web 规则管理，不符合“同一个 HTDY 系统、当前周期一个开关”的目标。

### 方案 D：把 pair 编码进 `scope_products`

拒绝。`jm@15m` 之类字符串会破坏 `scope_products` 的合法 symbol 语义和现有 validation。

### 方案 E：把 D1/W1 也在 Live 侧从 1m 聚合

拒绝。会形成第二套日/周事实口径，并重复夜盘、节假日、完整交易周与主力 owner 逻辑。

## 21. 风险

### 21.1 开关理解错误

最大的 UX 风险是用户误以为开关代表整个品种。Switch 必须明确显示当前 frequency。

切频只切换状态展示，不执行 mutation。

### 21.2 同时刻多周期事件

如果用户分别开启多个周期，整点可能同时触发多个 Event。设计选择“一个 HTDY frequency 一个 Event/一次通知”，不合并。

### 21.3 重绘造成历史图与当时提醒不一致

这是 HTDY original 的既有特性。AlertEvent 是 first-seen observation fact，不随历史重绘撤回。

### 21.4 D1/W1 Runtime 错过触发

继续遵守 no replay/backfill。Runtime 当时不在线可能错过该自然事件，第一版不为提高送达率引入队列或补发系统。

### 21.5 JSON Scope 与旧 scope_products 双事实风险

HTDY migration 后必须把 `scope_product_frequencies` 定为唯一 authority，并清空 HTDY 原 `scope_products`；Runtime、API、Web 不得一部分读旧字段、一部分读新字段。

SuBing 则只认 `scope_products`。任何混合状态必须 fail-closed，不做 union 或 fallback。

### 21.6 数据库 Event constraint 变宽后的 SuBing 保护

数据库无法再单独阻止同一 SuBing bar_end 的不同 frequency。该 invariant 必须由 `AlertRuleKind.FORMAL_SIGNAL` 的 Service consistency logic 和 regression tests 保持。

## 22. Canonical 变更原则

本 PR 只提交设计 Spec，不提前修改当前 canonical。当前代码与 canonical 仍以“HTDY Alert 15m + product scope”为现行事实。

只有实现真实完成并通过 Review 后，才在同一实现变更中同步更新 active canonical，把旧的 15m-only/product-only HTDY 描述收敛为：

```text
capability = Active60 × 7 frequencies
scope      = current symbol × frequency
D1/W1      = canonical-updated trigger
```

`STATUS.md` 只能记录已经发生的实现、验证、集成、发布和 Runtime 事实，不能因为 Spec 已批准就提前宣称完成。

## 23. Spec 自审结论

按以下项目重新自审：

- Placeholder：无 `TBD/TODO` 或未定义选择；
- 用户目标一致性：开关精确定义为“当前品种 × 当前周期”，不存在“一次打开七周期”的旧语义；
- Web/Runtime 一致性：Web pair Switch 对应后端真实 pair Scope，不存在前端按周期、Runtime 按品种的假隔离；
- 迁移安全：旧 HTDY product scope 只迁移成同品种 `15m` ON，不自动扩大通知范围；
- Scope authority：HTDY 与 SuBing 两种 Scope 字段严格互斥，混用 fail-closed；
- SuBing 隔离：现有品种级 Scope 与 bar-level formal Event identity 均保持；
- D1/W1：仍然只在盘后 Canonical 完成后触发；
- 多周期 Event：同一时间不同周期分别形成 Event 并分别推送，不合并；
- 数据边界：没有新增 Live D1/W1、第二套聚合、scheduler 或回放路径；
- 复杂度：新增一个轻量 JSON Scope 字段和 pair mutation endpoint，不新增 Scope 表或通用框架；
- Scope：仍是一份可独立实现的 Lane 3 HTDY capability/Alert 变更。

本轮 Review 修正了上一版 Spec 的核心错误：上一版把单个 HTDY Switch 定义成“当前品种七周期全部开启”，与用户实际操作目标不符。本版把用户 Gate 与 Runtime Gate 都统一成 exact `symbol × frequency`，并通过 migration 明确保留已有 15m Scope 而不自动扩张。

Spec 自审结果：可以进入用户 Review Gate；在用户批准前不得开始 Lane 3 实现。
