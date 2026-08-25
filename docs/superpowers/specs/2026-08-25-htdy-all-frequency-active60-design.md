# HTDY 全周期 × Active60 统一观察与 Alert 设计

状态：Proposed  
日期：2026-08-25  
设计基线：`develop@48d8bd512dc50b5e87bf524aed5edb448d85a5b1`  
任务等级：Lane 3（指标可信口径 + Alert Runtime + migration）

## 1. 背景与当前事实

当前火天大有（HTDY original）已经具备以下基础能力：

- Python Indicator Kernel `huotian_dayou_original_v0` 的 `supported_intervals` 已是正式七周期：`1m / 5m / 15m / 30m / 60m / 1d / 1w`；
- Web 侧 `calculateHuoTianDaYou()` 也是按传入 Bar 计算，本身没有 15m 专用公式；
- 当前 Web Overlay capability 却把 HTDY 限定为 `15m`，因此用户切换其他周期后会进入 unsupported 状态并停止绘制；
- 当前 Alert Rule `htdy_original_15m`、HTDY evaluator、Alert Runtime message parser、event-cutoff read window、通知文案均显式写死 15m；
- Market Live 当前发布 completed `1m`，并由 1m 派生并发布 `5m / 15m / 30m / 60m`；`1d / 1w` 不属于 Live Pub/Sub 派生面，而是在盘后 Canonical 维护中形成正式数据；
- 当前 `alert_events` 的唯一键为 `(rule_id, symbol, bar_end)`，如果同一品种在同一收线时刻多个周期同时触发 HTDY，会发生跨周期唯一键冲突；
- 当前 `operational_products.txt` 与 active universe 一致，共 60 个品种。产品覆盖应继续由该文件驱动，不在 HTDY 代码中硬编码“60”或具体品种列表。

本设计是新的 HTDY 单系统全周期方向，不恢复已经撤回的“四系统 Active60 全周期观察”方向。

## 2. 目标

本次目标只有一个：

> HTDY 在当前 operational universe 的全部品种、全部正式周期上统一具备“图表观察 + Alert 资格”；用户只通过 Web 中当前已有的 HTDY 品种开关决定该品种是否产生 HTDY Alert。

具体结果：

1. 用户选择“火天大有”后，可以在 `1m / 5m / 15m / 30m / 60m / 1d / 1w` 任意切换，Overlay 始终正常计算和显示，不再出现“当前周期不支持该 Overlay”。
2. 当前 60 个 operational products 全部具有 HTDY 全周期能力，不再存在 JM/15m 这种产品/周期限定。
3. Web 仍然只保留一个“火天大有”开关：
   - OFF：该品种七个周期全部不产生 HTDY Alert；
   - ON：该品种七个周期全部具有 HTDY Alert 资格。
4. 不增加“按周期开关”、不增加第二套 HTDY Rule、不拆分“观察版”和“预警版”。
5. HTDY original 仍是已知 future-looking / repainting 的 observation-only 指标；本次只扩大观察与提醒的产品/周期覆盖，不把它升级为正式回测、正式策略、交易信号或订单能力。

## 3. 非目标

本次明确不做：

- 不做每周期独立 Alert 开关；
- 不做 Alert 频率白名单配置页面；
- 不自动把 60 个品种全部打开提醒；
- 不做消息合并、节流、队列、retry、replay、backfill、outbox 或 fallback；
- 不新增 HTDY 派生表、第二套事件表、第二套 scheduler；
- 不修改 HTDY original 数学公式、XMA 语义、25 周期参数、3 连续 K 线观察判定；
- 不把 `continuous` 或指定 `contract` 变成 Alert 身份；Alert 继续是品种级 `actual_dominant` 当前 rank1 观察；
- 不改变 SuBing Alert 的 5m/15m 行为；
- 不做自动交易，`auto_order=false` 保持不变。

## 4. 统一 Capability Contract

### 4.1 周期集合

HTDY 的唯一正式周期集合固定为：

```text
1m | 5m | 15m | 30m | 60m | 1d | 1w
```

Web Overlay 与 HTDY Alert Rule 必须对这七个周期保持一致，不再分别维护“Web 支持周期”和“Alert 支持周期”两套业务口径。

实现可以因为数据到达方式不同而有不同触发入口，但不能形成不同的业务 capability。

### 4.2 品种集合

HTDY 不持有自己的品种名单。能力范围始终为：

```text
load_operational_products()
```

当前验收基线应读出 60 个品种；未来 `operational_products.txt` 合法变化时，HTDY 自动继承新的 operational universe，不要求同步修改 HTDY 常量。

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

原因是 Web 开关是“品种级开关”，不是“图表序列实例级开关”。如果让 Alert 跟随当前 `continuous` 或某个指定 `contract`，一个开关就无法稳定定义通知身份，也会产生重复和歧义。

因此，“图表观察和 Alert 不拆开”在本设计中精确定义为：**产品 × 周期 capability 不拆开**；Alert 的 actual-dominant 身份继续沿用既有业务合同。

## 5. Web 设计

### 5.1 HTDY Overlay

`RESEARCH_OVERLAY_DEFINITIONS.htdy.supportedFrequencies` 改为全部 `MARKET_FREQUENCIES`。

结果：

- 选择 HTDY 后切换任一正式周期，`researchOverlayCapability()` 都应返回 supported；
- `visibleMainIndicatorsForOverlay('htdy', ...)` 始终保留 `htdy`；
- 当前“当前序列或周期不支持该 Overlay”提示不应因 HTDY + 合法周期出现；
- optional EMA 行为保持现状；
- HTDY 的 repaint 风险提示、unstable tail 27 bars、observation-only 文案保持。

不新增新的 Overlay id，也不新增 HTDY 周期设置。

### 5.2 Alert 开关

继续复用现有 `ProductAlertRules` 的单个 HTDY `NSwitch`。

用户语义固定为：

```text
HTDY switch OFF
-> 当前品种不在 HTDY scope_products
-> 1m/5m/15m/30m/60m/1d/1w 全部不提醒

HTDY switch ON
-> 当前品种进入 HTDY scope_products
-> 七周期全部具备提醒资格
```

UI 不增加七个子开关。展示标签建议从“火天大有 · 15m”改为“火天大有 · 全周期”，避免把七周期全部堆在狭窄侧栏。

Overlay 的选中/取消与 Alert Scope 仍是两个不同用户动作：

- 选择 HTDY Overlay 只改变图表显示；
- HTDY Switch 才改变该品种是否提醒；
- 切换图表周期、图表序列或 Overlay 不得隐式改变 `scope_products`。

### 5.3 持久 Alert Marker

HTDY 的 persistent Alert marker 支持周期同步扩大到七周期。

同一 AlertEvent 只显示在与 `event.frequency` 相同的图表周期；不能把 15m Event 投影到 5m，也不能跨周期复制 marker。

## 6. Alert Rule 设计

### 6.1 保留单一 HTDY Rule

仍然只有一条 HTDY Rule，不按周期拆成七条。

本次**保留数据库稳定标识**：

```text
rule_code = htdy_original_15m
```

虽然名称包含历史 `15m` 后缀，但它已经是 production 持久身份，并被已有 `alert_rules / alert_events / Web` 引用。为避免把本次能力扩展与 Rule identity rename 绑成同一次生产迁移，本次不改 rule_code；其能力的权威定义改为 `input_frequencies`，代码中需明确标注该字符串是 legacy stable identity，不再代表当前周期范围。

未来如果确实需要清理命名，应单独做一次 Rule identity migration，而不是混入本任务。

`HTDY_RULE.input_frequencies` 改为正式七周期。

### 6.2 Web 开关是唯一用户级提醒 Gate

`AlertRule.enabled` 继续作为内部 Rule activation 状态，默认保持既有值；用户日常决定某个品种是否收到 HTDY 提醒，只通过 `scope_products` 的 Web 开关完成。

不新增 `scope_frequencies`、`frequency_enabled` 或其他隐藏用户配置。

现有 scope 必须原样保留：

- migration 不自动加入新的 59 个品种；
- 当前已经 ON 的品种在新 Runtime promotion 后，其 ON 语义会从“15m”扩大为“七周期”；
- 因为该语义会扩大既有开启品种的实际通知量，Runtime promotion 前必须只读核对当前 HTDY scope，并把这一变化作为人工 Gate 的显式审查项。

## 7. AlertEvent 身份迁移

### 7.1 问题

七周期后，同一品种可以在同一 `bar_end` 同时出现多个合法 HTDY Event，例如：

```text
10:00
-> 5m close
-> 15m close
-> 30m close
-> 60m close
```

当前唯一键：

```text
(rule_id, symbol, bar_end)
```

会错误地把不同周期视为同一个 Event。

### 7.2 新唯一键

AlertEvent 的业务身份改回：

```text
(rule_id, symbol, frequency, bar_end)
```

需要新增 Alembic migration：

1. 删除 `uq_alert_events_rule_symbol_bar_end`；
2. 创建 `uq_alert_events_rule_symbol_frequency_bar_end`；
3. ORM `UniqueConstraint` 同步；
4. `AlertService._event_by_identity()` 和 duplicate consistency 检查同步加入 `frequency`。

已有 Event 数据天然满足更宽的新唯一键，不需要修改历史 Event 内容，也不需要 backfill。

### 7.3 幂等语义

- 同 rule + symbol + frequency + bar_end 再次到达：不重复 Event、不重复通知；
- 同 rule + symbol + bar_end 但 frequency 不同：允许分别创建 Event，并分别进行一次通知尝试。

不做跨周期通知合并。

## 8. HTDY Evaluator 设计

把 `HtdyOriginal15mEvaluator` 收敛为一个可处理七周期的 HTDY original evaluator，但仍然只处理单个 completed event bar。

固定合同：

```text
indicator      = huotian_dayou_original_v0
series_kind    = actual_dominant
frequency      = 当前 event frequency，且必须属于七周期 allowlist
context_bars   = 32
cutoff         = 当前 completed event bar_end
result         = 只读取计算结果最后一根 buy/sell observation
auto_order     = false
```

32 bars 不随周期改变；算法仍按“Bar 数”而不是自然时间长度计算。

Evaluator 不扫描 repaint 区域找旧信号，不撤销旧 AlertEvent，不把未来重新计算后的历史形态当成新事件。

## 9. Runtime 触发设计

七周期的数据到达方式并不相同，因此 Runtime 使用两个现有事实入口，但对外仍是同一条 HTDY Rule 和同一品种开关。

### 9.1 日内五周期：Live completed-bar trigger

以下周期直接使用现有 `live:bar:{symbol}:{frequency}`：

```text
1m | 5m | 15m | 30m | 60m
```

改动：

- Alert message parser 接受上述五个日内周期；
- Rule definition 的 frequency filter 决定 HTDY 是否处理；
- SuBing 仍只接受 5m/15m，现有同 boundary 抑制规则保持不变；
- HTDY `_evaluate_htdy()` 使用 event_frequency，而不是固定 M15；
- `window_matches_event` 使用请求 frequency，而不是固定 `15m`。

这不会新增第二个 Live aggregator；Market Live 已经从 completed 1m 形成 5m/15m/30m/60m。

### 9.2 1d / 1w：Canonical-updated trigger

不在 Live Market 中再造 D1/W1 聚合，也不把 transient 1m 聚合结果冒充正式 D1/W1。

复用现有盘后成功后的 `market:state` 发布点，增加一个非敏感、明确的触发原因：

```json
{
  "trading_day": "YYYY-MM-DD",
  "reason": "canonical_updated"
}
```

Alert Runtime 同时订阅该现有 channel，并且只在 `reason=canonical_updated` 时执行 HTDY D1/W1 检查；Live Runtime 发布的普通 `market:state`（例如交易日切换）不触发 D1/W1 Alert。

盘后触发流程：

```text
HistoricalDataManager.update passed/noop
-> Canonical 已处于可读状态
-> market:state(reason=canonical_updated, trading_day=T)
-> Alert Runtime 读取 enabled HTDY rule + scope_products
-> 对每个 scope product 检查 D1
-> 对每个 scope product 检查 W1
-> 只接受 latest bar.trading_day == T 的 completed bar
-> current-bar evaluator
-> AlertEvent
-> one-shot PushPlus
```

`W1` 仍完全复用 `MarketDataService` 已有“完整交易周 + weekly owner”规则，不在 Alert 内重新判断周线主力归属。

`latest bar.trading_day == T` 是 no-backfill 边界：

- 周一到周四如果最新 W1 仍属于上周，不允许补发；
- Alert Runtime 如果在周线形成当天宕机并错过 Pub/Sub，不在下一交易日补发；
- 重复收到同一 `canonical_updated` 只依靠 Event 唯一键幂等，不产生重复通知。

这保持现有 Alert V2 的“启动后新事实、无 replay/backfill”原则。

### 9.3 为什么不直接把 D1/W1 放进 Live derive

拒绝该方案，原因是：

- 正式 D1 本来就来自交易所日行情，W1 来自完整同源 D1；
- 在 Live 侧再从 1m 维护 D1/W1 会出现第二套日/周口径；
- 还要额外处理夜盘、节假日、完整交易周和跨主力周 owner，复杂度明显高于当前个人工作站需要。

## 10. Market event-cutoff read 设计

当前 `MarketReadService.bars_until()` 只允许 `actual_dominant + 15m`，必须泛化为 HTDY 七周期 event-cutoff reader，但仍保持 fail-closed。

### 10.1 日内

`1m/5m/15m/30m/60m`：

- 读取 Canonical historical page；
- 合并当前交易日 Live Redis 同周期 bar；
- 精确截断到 event `bar_end`；
- 必须存在 exact cutoff bar；
- current rank1 contract 仍从当天 immutable Live subscription snapshot 唯一解析；
- 不跨频回退，不自己聚合。

### 10.2 D1/W1

`1d/1w`：

- 只读 Canonical `actual_dominant`；
- 不依赖可能已经 cleanup 的 Live subscription；
- contract identity 从 `MarketDataService` 返回的 `resolved_contract_segments` 唯一解析；
- exact cutoff bar、trading_day、segment owner 任一不唯一时 fail-closed；
- W1 的 owner 只认 `MarketDataService` 已实现的完整交易周解析，不在 Alert 重复实现。

### 10.3 不可用输入

少于 32 根、exact cutoff 缺失、主力身份不唯一、Canonical/Live 读取失败时：

- 不创建 Event；
- 不发送通知；
- 不使用其他周期替代；
- 不补零、不猜合约；
- 沿用现有 Rule 故障隔离与公开 processing failure 观察，不新增第二套 unavailable 状态表。

## 11. Notification 设计

HTDY 继续发到既有 `htdy_observers` Topic，仍然是每 Event 最多一次 provider request。

修改 `_format_htdy_message()`：

- 接受七周期；
- 文案使用 `message.frequency` 动态显示，不再写死 `15m`；
- 继续显示品种、主力合约、收线时间和“研究观察，非交易指令”；
- provider accepted 仍不等于微信送达。

同一时刻多个周期分别触发时，允许分别发送。例如 10:00 同时出现 15m 与 60m HTDY observation，会得到两个不同 Event/通知。

本次不做跨周期合并，因为合并会引入等待窗口、状态缓存和通知时序新规则，与当前“一次 Event 一次尝试”的简单合同冲突。

## 12. HTDY original 重绘语义保持不变

扩大周期范围不能掩盖 original 的已知风险：

- symmetric XMA 仍有 future dependency；
- current last bar 使用当时可见的 clipped window；
- 后续新 Bar 到达后，历史 HTDY 可能重绘；
- AlertEvent 表示“当时该 completed bar 首次观察到的事实”，一旦创建保持 immutable；
- 不因为后续重绘撤回 Event，也不发送“撤回提醒”；
- Web 历史图可以按当前完整窗口重新计算，因此历史图形与当时 AlertEvent 可能不同；Alert marker 继续作为当时事实保留。

这仍然不是正式策略有效性、回测或交易证据。

## 13. Migration 与兼容性

本任务需要一个 Alert Application Domain migration，但不新增表、不新增列。

允许修改：

- AlertEvent unique constraint；
- ORM / service 的 Event identity；
- 与该 constraint 对应的 migration test。

禁止：

- 修改已有 Event 内容；
- 自动扩张 `scope_products`；
- 删除历史 Event；
- 生产 migration 未经独立明确执行意图直接运行。

由于 `rule_code` 本次保持不变，新 constraint 可以先应用而不破坏旧 15m Runtime 的 Rule lookup；这降低本地单用户发布时的耦合风险。

## 14. 预计实现范围

实现阶段预计只触及现有模块，不创建新子系统：

```text
Web
- apps/quant-web/src/utils/mainIndicators.ts
- apps/quant-web/src/utils/alertRules.ts
- apps/quant-web/src/utils/alertMarkers.ts
- ProductAlertRules 及相关 unit/e2e tests

Alert
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
- STATUS.md（只有实现/集成的真实状态发生后才更新）
```

如果实现过程中发现必须新增 scheduler、queue、第二套 daily/weekly aggregation 或新 Application Domain，应停止并回到设计 Gate，不得静默扩范围。

## 15. 验收标准

### 15.1 Web

1. 当前 operational 60 中任一品种选择 HTDY 后，七个正式周期都能显示 HTDY，且不出现 HTDY unsupported warning。
2. HTDY Overlay 在 `continuous / actual_dominant / contract` 三种现有图表序列均保持可用。
3. Web 只出现一个 HTDY Alert Switch；不出现周期子开关。
4. OFF 后该品种七周期均不具有 HTDY Alert scope；ON 后七周期统一具有资格。
5. HTDY persistent Alert marker 在七周期中按 Event 自身 frequency 精确显示。

### 15.2 Backend / Alert

1. HTDY Rule frequency capability 精确等于七个正式周期。
2. HTDY evaluator 在七周期使用同一 original Kernel、同一 32-bar current-event cutoff 语义。
3. Alert Runtime 接受 completed `1m/5m/15m/30m/60m` live bar；SuBing 仍只消费 5m/15m。
4. `market:state` 只有 `reason=canonical_updated` 才能触发 D1/W1；普通 state 变化不能触发。
5. D1/W1 只有 latest canonical bar 的 `trading_day` 等于本次 canonical-updated trading day 才可评估，禁止补发旧日/旧周。
6. 同一 HTDY rule + symbol + bar_end 的不同 frequency 可以各自创建 Event；同 frequency 重复输入仍幂等且不重发。
7. Web Switch OFF 的品种在任何周期都不创建 HTDY Event；ON 的品种才进入评估。
8. 非 operational product 继续 fail-closed。
9. 通知文案动态显示实际 frequency；topic audience、one-shot、provider acceptance 语义不变。
10. 无 replay/backfill/retry/outbox/queue/fallback/order。

### 15.3 数据与因果

1. 日内只消费同周期 completed Bar，不跨频回退。
2. D1/W1 只消费正式 Canonical；W1 owner 由 `MarketDataService` 唯一解析。
3. exact cutoff、rank1 identity、coverage 或 32-bar context 不完整时不产生 Event/通知。
4. original 的 future-looking/repainting metadata、24-bar future dependency、27-bar Web repaint scan zone 保持不变。
5. `auto_order=false`。

### 15.4 Migration

1. PostgreSQL constraint 为 `(rule_id, symbol, frequency, bar_end)`。
2. migration 前已有 Rule、scope、Event 数量与内容保持不变。
3. migration 不自动增加任何 scope product。
4. isolated PostgreSQL migration test 必须覆盖 upgrade 和新唯一键行为。

## 16. 验证要求

这是 Lane 3 变更，不能只跑前端测试。

实现阶段至少需要：

- HTDY Kernel / policy focused tests；
- Alert registry / evaluator / runtime / service / notification focused tests；
- MarketReadService / Live Market / after-market focused tests；
- Alembic migration tests，使用隔离 PostgreSQL；
- Web mainIndicators / alertRules / alertMarkers / scope unit tests；
- Web Playwright 覆盖 HTDY 七周期切换 + 单 Switch 行为；
- full non-isolated backend suite；
- Ruff；
- Mypy；
- Web full unit；
- Web production build；
- full Playwright；
- OpenSpec validate；
- secret scan；
- diff / canonical consistency checks。

代码完成后，还应做一次**只读** Active60 × 七周期 capability matrix 验证：确认每个 operational product 都能走到合法查询/评估入口；真实数据覆盖不足必须返回明确不可评估，不得伪造成功。该矩阵只证明 capability coverage，不证明策略有效、盈利或可交易。

真实通知 canary、production migration、Scope mutation、release/tag、Runtime switch/promotion 都是独立外部 Gate，本 Spec 与自动化测试不授权执行。

## 17. 发布与 Runtime Gate

建议流转：

```text
Spec approved
-> Lane 3 implementation
-> focused + full verification
-> independent Review
-> develop integration
-> release candidate
-> 用户批准 production migration / release（按实际发布流程分别取得明确意图）
-> 用户批准 Runtime promotion
-> 只读核对当前 HTDY scope
-> 启动新 Runtime
-> 自然事件观察
```

特别注意：当前已经处于 HTDY scope 的任何品种，在新 Runtime 上会从“仅 15m”变成“七周期”。这不是 migration 自动扩 scope，但属于同一开关语义的能力扩大，必须在 Runtime promotion 审查中明确展示当前 scope。

release 批准、production migration 与 Runtime promotion 不能由本 Spec、代码合入或测试结果互相推导。

## 18. 方案比较与取舍

### 方案 A：单 HTDY Rule + 单品种 Switch + 双事实触发入口（推荐）

- Web/Alert 都支持七周期；
- 日内使用现有 Live bar；
- D1/W1 使用现有盘后 Canonical-updated seam；
- 一个 Rule、一个 scope、一个开关；
- 只需要调整 Event identity，不创建新表或 scheduler。

优点：最贴合用户目标，且最大程度复用现有 Market/Alert 基础设施。  
缺点：D1/W1 提醒发生在盘后 Canonical 更新完成后，而不是 Session 最后一根 1m 到达瞬间。

### 方案 B：把 D1/W1 也在 Live 侧从 1m 聚合

拒绝。会形成第二套 D1/W1 口径，增加完整交易日、完整交易周、节假日和主力 owner 逻辑，破坏当前“D1 来自交易所日行情、W1 来自完整 D1”的数据边界。

### 方案 C：七周期拆成七条 Rule / 七个开关

拒绝。直接违反“图表观察和 Alert 不拆开、是否提醒只看一个 Web 开关”的目标，还会放大个人项目维护复杂度。

## 19. 风险

### 19.1 通知量明显上升

HTDY Switch ON 代表七周期同时开启，尤其 1m 可能显著增加事件数量。第一版不加入节流或跨周期合并；用户通过品种开关控制是否接受该品种的全周期提醒。

### 19.2 同时刻多周期事件

整点可能同时触发多个周期。设计选择“一个 frequency 一个 Event/一次通知”，通过新 Event unique identity 保证合法共存与同频幂等。

### 19.3 重绘造成历史图与当时提醒不一致

这是 HTDY original 的既有特性，不是本次扩周期引入的新算法风险。UI/文档必须继续明确：AlertEvent 是 first-seen observation fact，不是可回测信号，也不会随历史重绘撤回。

### 19.4 D1/W1 Runtime 错过触发

继续遵守无 replay/backfill：Runtime 当时不在线就可能错过该自然事件。第一版不为提高送达率引入队列或补发系统；这是刻意保持的简单边界。

## 20. Canonical 变更原则

本 PR 只提交设计 Spec，不提前修改当前 canonical。当前代码与 canonical 仍以“HTDY Alert 15m”为事实。

只有实现真实完成并通过 Review 后，才在同一实现变更中同步更新 active canonical，把旧的 15m-only 描述收敛为本 Spec 的七周期合同；`STATUS.md` 只能记录已经发生的实现、验证、集成、发布和 Runtime 事实，不能因为 Spec 已批准就提前宣称完成。

## 21. Spec 自审结论

按以下四项完成自审：

- Placeholder：无 `TBD/TODO` 或依赖未定义选择；
- Internal consistency：Web 与 Alert 的产品/周期集合一致；Alert actual-dominant 身份、D1/W1 Canonical 数据边界与现有 Market Foundation 不冲突；
- Scope：单一 HTDY 能力扩展，可由一份 implementation plan 承载；未恢复四系统全周期方向；
- Ambiguity：明确了“一个 Switch=一个品种七周期”、Event 跨周期唯一键、D1/W1 触发时机、Rule code 保留策略、scope 不自动扩张和 no-backfill 语义。

Spec 自审结果：可以进入用户 Review Gate；在用户批准前不得开始 Lane 3 实现。