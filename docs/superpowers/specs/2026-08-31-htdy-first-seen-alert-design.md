# HTDY Forward-Only First-Seen Alert Design

日期：2026-08-31

状态：Design approved for planning

最终文档基线：`develop@774e0dd16e6614877d19886627878751190d78ce`

## 1. 背景与问题

HTDY 原始指标 `huotian_dayou_original_v0` 使用 centered XMA。production kernel 已冻结：双 XMA25 对单点最多有 24 根未来 Bar 依赖，`CONFIGURED_REPAINT_SCAN_ZONE_BARS=27`，因此历史 K 线上的 `buy_observation` / `sell_observation` 会在后续 Bar 到来后出现、消失或改变。

当前 Market Web 会对当前已知整段 Bar 重新计算 HTDY，所以用户可能在旧 K 线上看到新的“买观察/卖观察”。当前 Alert Runtime 则只读取 `result.buy_observation[-1]` / `result.sell_observation[-1]`，只在 incoming completed Bar 自身当刻触发 Event。这样形成了两个不同事实：

- Web：当前已知信息下的 retrospective/repainting observation；
- Alert：current-bar-only observation。

结果是 Web 后来出现历史观察，但当时没有生成 `AlertEvent`，也没有 PushPlus。对于“火天大有出现观察就提醒我”的产品目标，这个时间语义不够一致。

本设计只修正 HTDY Alert 的“何时算系统真正第一次看到某个观察”语义，不修改 HTDY 公式、Scope、audience、transport、Event 表结构或 Runtime trigger seam。

## 2. 目标

将 HTDY Alert 从 `current-bar-only` 收敛为：

```text
forward-only first-seen repaint observation
```

即每次现有合法 trigger 到达时，只比较“上一 prefix”与“当前 prefix”，识别本次新出现的 observation：

1. 当前最新 Bar 首次出现 buy/sell；
2. 最近 repaint zone 内的旧 Bar 因当前新 Bar 到达，由无观察变为有观察。

第一次识别后创建 immutable `AlertEvent`，Event 以后不因重绘消失、恢复或反向而撤回或修改，也不重复通知。

### 成功标准

- Web 中因后续 Bar 首次重绘出来的 HTDY 观察，在其首次被 Runtime 真实看到时形成 `AlertEvent` 并进入现有 one-shot PushPlus 链路；
- `bar_end` 表示观察 K 线时间，`detected_at` 表示 Runtime 首次识别时间，两者不再混淆；
- Runtime 启动、replay、backfill、repair、EOD recalculation 不补历史 Event 或通知；
- 同一 `rule + symbol + frequency + observation bar_end` 最多冻结一条 HTDY Event；
- 不改变现有 `jm × 15m` production Scope，不自动扩大到其他 symbol/frequency。

## 3. 非目标与禁止范围

本任务不做：

- 修改 HTDY 原始 XMA、黄/白 K、第三根连续观察公式；
- 新建 first-seen 表、ledger 表、queue、outbox、notification 表或第二套 SignalEvent；
- 恢复 2026-07 的旧 `StrategySignal/SignalEvent` first-seen 实现；
- migration、production DB/Redis/Scope 写入；
- retry、replay、backfill、fallback、补发；
- Scope、audience、Topic、PushPlus provider 配置变化；
- 新 scheduler 或新的 D1/W1 事实链；
- `main`、tag、release、Runtime promotion；
- 任何订单能力。

## 4. 保持不变的现有合同

以下 identity 与边界保持原样：

- HTDY Rule code：`htdy_original_15m`；
- HTDY capability：`1m/5m/15m/30m/60m/1d/1w`；
- HTDY Scope authority：`scope_product_frequencies` 的 `symbol × frequency`；
- SuBing Rule/Scope/Runtime 完全独立；
- Alert application domain 仍只有 `alert_rules` 与 `alert_events`；
- Event 先 commit，随后最多一次 transport；
- intraday 仍只消费同周期 completed Live Bar；
- D1/W1 仍只响应 `market:state(reason=canonical_updated)` 并读取 Canonical；
- provider accepted 仍不等于微信送达；
- `auto_order=false`。

当前 production Scope 仍为 `jm × 15m`。虽然 First-Seen detector 对 HTDY 七周期使用同一业务语义，只有显式启用的 pair 才允许创建 Event/通知。

## 5. First-Seen 业务语义

### 5.1 Trigger 语义

不新增 trigger。

Intraday：

```text
live:bar:{symbol}:{frequency}
-> completed same-frequency Bar
-> exact Scope check
-> HTDY first-seen evaluation
```

D1/W1：

```text
market:state(reason=canonical_updated)
-> existing Canonical window
-> exact Scope check
-> HTDY first-seen evaluation
```

### 5.2 Prefix 对比

每个 eligible trigger 只比较两个 prefix：

```text
previous_prefix = 当前读取窗口去掉最新一根 Bar
current_prefix  = 当前读取窗口
```

不得读取未来 trigger，不得扫描启动前完整历史，不得通过 Event 表反推指标状态。

### 5.3 Candidate 与最终 First-Seen 规则

Prefix detector 由两部分产生本次候选：

**A. 当前最新 Bar**

如果 `current_prefix` 最后一根 Bar 当前有 buy/sell observation，则它是本次 candidate。该行为保留现有 current-bar Alert 能力。

**B. Repaint zone 内旧 Bar**

只比较 `previous_prefix` 最后 `CONFIGURED_REPAINT_SCAN_ZONE_BARS=27` 根与 `current_prefix` 中同一 `bar_end` 的 observation：

```text
previous observation = empty
current observation  = buy / sell / buy+sell
=> prefix transition candidate
```

以下不会产生新的 prefix transition candidate：

- buy -> empty；
- sell -> empty；
- buy -> sell；
- sell -> buy；
- buy -> buy+sell。

“已有 observation -> 消失 -> 后来再次出现”需要单独区分两层语义：

- 纯 prefix detector 在再次出现的那一次可能再次看到 `empty -> non-empty` transition；
- 但现有 `AlertEvent` identity `(rule_id, symbol, frequency, bar_end)` 是最终 First-Seen authority；只要该 observation Bar 已有 Event，Persistence 必须 immutable no-op，不修改、不撤回、不再次通知。

因此系统级 First-Seen 的定义始终是：

> 同一 observation Bar 第一次从无持久 Event 进入有持久 Event；不是方向 revision ledger，也不是每次重绘 transition ledger。

### 5.4 多 candidate

一次 incoming Bar 可能让多根旧 Bar 同时首次出现观察。Runtime 按 `observation bar_end` 升序确定性处理；每个尚无持久 Event 的 candidate 对应一条独立 Event 和现有 one-shot notification attempt，不做聚合通知。已存在 Event 的 candidate 由 Persistence no-op 丢弃，不进入 transport。

## 6. 计算窗口与 parity

现有 evaluator 的 `32` Bar 上下文只为 current last-bar parity 服务。First-Seen 需要同时保证最近 27 根 candidate 及第三根连续判断的历史上下文。

本设计固定：

```text
HTDY_FIRST_SEEN_CONTEXT_BARS = 64
HTDY_REPAINT_SCAN_BARS = production kernel CONFIGURED_REPAINT_SCAN_ZONE_BARS (=27)
```

64 不是新指标参数，不改变公式；它只是 bounded evaluation window。实现必须通过测试证明：

```text
64-bar bounded prefix comparison
==
full-history prefix comparison
```

对最近 27 根可扫描 observation 完全一致。若该 parity 不能证明，任务 fail-closed，不得以 64 作为经验值继续。

窗口不足 64 根时不允许 historical repaint scan。为避免改变现有 warm-up 行为，实现可保留 current-bar 32-Bar evaluation；只有上下文达到 64 时才增加 historical first-seen candidates。不得因 first-seen 扩展让原有 current-bar capability 倒退。

## 7. Observation Bar 的真实合约身份

First-Seen candidate 的 `bar_end` 可能早于当前 incoming Bar，甚至跨交易日或 rank1 rollover。现有 `MarketReadWindow.contract` 只描述当前窗口/trigger 的 contract，不能无条件用于旧 candidate。

因此 First-Seen candidate 必须携带其 observation Bar 的真实 `actual_dominant rank1` contract identity。

实现要求：

- Market read seam 在返回 bounded Alert window 时，同时提供与 `bars` 一一对齐的 contract ownership；
- Historical 部分只使用 `MarketDataService` 已返回的 `resolved_contract_segments` 解析 ownership；
- Live 当前 trading day 使用既有 subscription contract；
- 同一 bar 的 Historical/Live ownership 冲突、无法唯一解析或数组不对齐时 fail-closed；
- consumer 不得自行查文件、glob 或猜主力。

这样 Event 的 `contract/trading_day/bar_end` 始终描述 observation Bar 本身，而 `detected_at` 描述第一次识别时刻。

## 8. Event 冻结与幂等

不修改 `alert_events` schema。继续使用现有 HTDY unique identity：

```text
(rule_id, symbol, frequency, bar_end)
```

其中 `bar_end` 现在明确命名为 **observation bar end**。

### 8.1 新 Event

首次创建保存：

- rule_id；
- symbol；
- frequency；
- observation bar 的 contract；
- observation bar 的 trading_day；
- observation `bar_end`；
- 首次识别时冻结的 `result_codes`；
- `detected_at = processing_now`；
- `notification_attempted_at = processing_now`。

### 8.2 已有 Event

对 HTDY indicator observation，已有同 identity Event 即表示该 observation bar 已 first-seen：

- 不修改 Event；
- 不比较或改写后续 repaint direction；
- 不再次生成 message；
- 不把正常 repaint revision 记成 consistency failure。

该 no-op 必须只适用于 indicator-observation first-seen identity；SuBing Strategy Event 的 action consistency 规则不变。

数据库 race 下仍须按同一 identity 读回并 no-op；真正 schema/identity/contract 类型异常继续 fail-closed。

## 9. Runtime 与启动边界

现有 startup drain 继续 `emit_events=False`。First-Seen 不允许：

- 启动时扫描历史并补 Event；
- restore/catch-up 补通知；
- 根据当前 Web 上已有 marker 补发；
- 根据旧 AlertEvent 重放 transport。

启动后的第一根新 trigger 只比较该 trigger 的 previous/current prefix。如果一个历史 observation 在 previous prefix 已经存在，则不算本次 first-seen。

## 10. Notification 语义

PushPlus route、audience、Topic 和 one-shot transport 都不变。

HTDY message 必须同时表达两个时间：

```text
【归一量化】JM 焦煤

火天大有 · 卖出观察
主力：JM2701
观察K线：15m · 09:45
首次识别：10:15
研究观察，非交易指令
```

要求：

- `观察K线` 来自 Event `bar_end`；
- `首次识别` 来自 Event/request `detected_at`；
- 两者都按 Asia/Shanghai 展示；
- current-bar first-seen 时两者可以相同；
- SuBing message 文案不因本任务变化。

`AlertNotificationMessage` 可增加明确的 `detected_at` fact，但不得新增 provider-specific 字段。

## 11. Web 语义

当前 Web 已有两种不同 marker 来源，本任务不重做 marker 架构：

1. HTDY overlay 的 retrospective/repainting arrow；
2. persistent `AlertEvent` square marker。

继续保持两者独立。只加强 persistent marker 的 tooltip，使用户能直接看到：

- `实时首次识别 / 持久 AlertEvent`；
- observation result；
- observation contract；
- observation bar time；
- `detected_at` first-seen time。

不得把 retrospective marker 冒充 Event marker，也不得因为 Web 当前重绘结果与冻结 Event 不一致而隐藏或改写 Event。

API 当前已经返回 `detected_at`，不需要为此新增 HTTP endpoint 或 response schema。

## 12. 错误与 fail-closed

以下情况不得创建 Event 或发送通知：

- Rule disabled / pair Scope disabled；
- MarketReadWindow identity 不匹配；
- 64-Bar first-seen scan 所需 contract ownership 不完整或不唯一；
- current/latest cutoff 与 trigger 不一致；
- candidate observation bar 无法解析真实 contract；
- evaluator 返回非法 result codes；
- Event persistence 发生非幂等数据库错误；
- notification preparation 缺少 taxonomy 或时间事实。

Event 已成功 commit 后 transport 失败仍遵守现有合同：记录 notification failure，不 retry、不 replay、不删除 Event。

## 13. 测试合同

至少覆盖：

1. current Bar 首次 buy/sell -> Event + one-shot message；
2. append 新 Bar 后，旧 Bar empty -> sell -> Event；
3. old sell -> empty -> 不撤回；
4. old sell -> empty -> sell -> 不重复；
5. old buy -> sell / sell -> buy -> 既有 first-seen Event 不修改、不报 consistency drift；
6. empty -> buy+sell -> 一个 Event，两个 result_codes；
7. 同一 trigger 多 candidate -> 按 observation bar_end 升序创建；
8. 27-Bar repaint zone 边界内变化可发现，边界外不扫描；
9. 64-Bar bounded 与 full-history 最近 27 根 prefix diff parity；
10. 32~63 Bar 只保留 current-bar 能力，不做不可靠 historical scan；
11. observation candidate 跨 trading day 仍绑定正确 rank1 contract；
12. candidate 跨 rank1 rollover 时绑定 observation Bar 的 contract，不绑定 trigger contract；
13. contract ownership 缺失/冲突 fail-closed；
14. Scope OFF -> 不 market-read/evaluate/Event/send；
15. startup drain / catch-up `emit_events=False` -> 零 Event/零通知；
16. 重复 live message / Runtime restart -> Event 幂等；
17. transport failure -> Event 保留、无 retry/replay；
18. D1/W1 继续只由 `canonical_updated` trigger，First-Seen 语义与 intraday 一致；
19. SuBing Event/notification/runtime tests 全部不回归；
20. Web retrospective arrow 与 persistent square marker 来源不混合，persistent tooltip 显示 observation/detected 两个时间。

## 14. Canonical / 文档同步

实现完成时只更新真正发生语义变化的 active canonical：

- `AGENTS.md`：HTDY Alert 明确 forward-only first-seen、no retraction/no backfill；
- `PROJECT_SOURCE.md`：HTDY Formal Event 的 first-seen 时间语义；
- `DECISIONS.md`：长期冻结 `bar_end=observation time`、`detected_at=first-seen time`；
- `TESTING.md`：仅在新增/调整验证命令确有必要时更新。

`STATUS.md` 只有在真实 release/Runtime/evidence 状态发生变化时才更新；单纯 code/test complete 不提前写 Runtime Ready。

## 15. Gate 与完成边界

本设计属于 Lane 3，因为它改变可信 Alert 语义并最终影响真实通知。

实现阶段可以在独立 task branch/worktree 完成代码、测试、Review，并在用户 Gate 后集成 `develop`。以下仍是独立 Gate：

- production DB/Scope mutation：本设计不需要，禁止执行；
- 真实 PushPlus send：禁止在实现/测试中执行；
- release main/tag：另行批准；
- Runtime promotion：另行批准；
- 下一次自然 `jm × 15m` completed Live first-seen evidence：只能在已批准 Runtime 后自然取得，不用 replay/canary/手工触发替代。

## 16. Acceptance

Spec 验收必须满足：

```text
HTDY formula unchanged
Rule/Scope/audience unchanged
No migration
No new persistence domain
Forward-only prefix-diff first-seen
27-bar repaint scan
64-bar parity proved before use
Observation contract identity preserved
Event first-seen freeze/no retraction
No startup backfill/replay/retry
bar_end / detected_at semantics explicit
Web retrospective vs persistent Event distinct
SuBing unchanged
```

只有上述合同全部由代码和测试证明后，才允许进入独立 Lane 3 Review；Review 通过仍不等于 release、Runtime promotion 或真实通知授权。
