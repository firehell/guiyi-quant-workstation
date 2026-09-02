# 苏冰同花顺 15m 预警 V1 — Strategy Observation Spec

状态：`SPEC_READY_FOR_USER_REVIEW`

日期：2026-09-02

Issue：#307

规划基线：`develop@8a05ae1a3c8c25c56428874e00fa99260a4708e1`

任务车道：Lane 3

产品身份：`subing_ths_alert_15m_v1`

公式身份：`subing_ths_15m_v1`

---

## 1. 产品目标

本 Spec 定义一个全新的、最小化的苏冰预警产品。它只解决一个问题：

> 对 `operational_products.txt` 授权的国内期货品种持续盯盘；每根正式 completed 15m K 完成后，按用户正在同花顺期货通使用的 MACD + MA21 公式判断；出现信号时创建正式 AlertEvent、最多尝试一次 PushPlus，并在 Market Web 中显示，最终是否交易由用户人工判断。

稳定闭环只有：

```text
operational products
→ completed actual_dominant 15m
→ 同花顺公式
→ 苏冰多/空预警
→ immutable AlertEvent
→ one-shot PushPlus
→ Market Web
→ 用户人工判断
```

本产品不是交易策略执行系统，不模拟持仓，也不创建订单。

---

## 2. 与旧苏冰的关系

当前 active canonical 已退役既有策略域，并规定未来策略/观察产品必须使用新身份、新合同和新版本。

因此本任务：

- 不恢复 `subing_strategy_v1`；
- 不恢复旧 Daily Watch、5m/15m Factor、Lifecycle、Action、Episode、Position、Historical Strategy Projection、Strategy Runtime、Strategy Scope、Strategy API/CLI/Web 或派生 cache；
- 不继续旧 `subing_watch_15m_v1` Implementation Program；
- 不复用已退役策略模块作为隐藏实现；
- 只允许复用通用 MarketDataService、通用指标 primitive、Alert Application Domain、PushPlus transport 和 Market Web 基础设施。

本 Spec 与 Issue #307 是新的 active 设计 authority。Issue #286 及旧 Watch 设计只保留 Git 历史语义，不再作为实现依据。

---

## 3. V1 身份与用户语义

固定身份：

```text
public_name      = 苏冰预警
rule_code        = subing_ths_alert_15m_v1
formula_version  = subing_ths_15m_v1
kind             = indicator_observation
series_kind      = actual_dominant
frequency        = 15m
completed_only   = true
auto_order       = false
```

用户可见语义只有：

```text
15m 多头预警
15m 空头预警
```

不得描述成建多、建空、开仓、平仓、持仓、止盈止损、仓位建议、目标价或自动交易信号。

`buy` / `sell` 只作为 AlertEvent 的内部方向结果码，不代表系统执行交易。

---

## 4. 唯一正式公式

用户提供的同花顺期货通公式是 V1 唯一业务来源：

```text
DIFF = EMA(CLOSE, 12) - EMA(CLOSE, 26)
DEA  = EMA(DIFF, 9)
MACD = 2 * (DIFF - DEA)
MA21 = MA(CLOSE, 21)

BUY  = CROSS(DIFF, DEA) AND CLOSE > MA21
SELL = CROSS(DEA, DIFF) AND CLOSE < MA21
```

其中：

```text
MA(CLOSE, 21) = SMA21
```

不是 EMA21。

原公式中的 `幅度`、`偏移`、`DRAWTEXT` 和零轴绘制只服务于图形展示，不属于预警 Gate。

### 4.1 CROSS 精确定义

```text
golden_cross[t] =
    DIFF[t-1] <= DEA[t-1]
    AND DIFF[t] > DEA[t]

dead_cross[t] =
    DIFF[t-1] >= DEA[t-1]
    AND DIFF[t] < DEA[t]
```

正式 Candidate：

```text
LONG_ALERT[t] = golden_cross[t] AND close[t] > SMA21[t]
SHORT_ALERT[t] = dead_cross[t] AND close[t] < SMA21[t]
```

边界固定：

- `close == SMA21`：不触发；
- 当前 `DIFF == DEA`：不算完成 CROSS；
- 上一根或当前任一必需指标未 ready / invalid：不触发；
- 同一 completed 15m Bar 不允许同时生成 long 和 short；若实现产生双向结果，视为公式一致性错误并 fail-closed。

---

## 5. V1 禁止隐藏过滤

正式 Candidate Gate 只能来自第 4 节。

以下任何内容都不得参与 Candidate：

```text
MACD 是否靠近零轴
MACD 柱强弱
EMA21
MA21 斜率
5m / 30m / 60m / D1 共振
Daily Watch
Range Detector
震荡过滤
成交量 / OI / 量比
ATR 距离
前高前低
突破强度
三根 K 确认
评分
历史胜率
```

未来如需增加过滤，必须建立新的 `formula_version`，不能静默修改 `subing_ths_15m_v1`。

---

## 6. 公式 Kernel 与数值合同

### 6.1 单一正式 authority

新增一个纯计算、无 I/O 的 `SubingThs15mKernel`，作为 `subing_ths_15m_v1` 唯一正式公式 authority。

Kernel 内部复用现有 Quant Core：

- `initial_ema_state` / `step_ema`；
- `initial_macd_state` / `step_macd`；
- 一个最小通用 SMA21 incremental primitive（若实现时已有等价 primitive 则直接复用）。

Alert evaluator 只负责输入身份校验和调用 Kernel；API、Web、notification formatter 不得复制公式。

这样避免把当前通用 `MACD_VERSION` 或 evaluator 内部实现本身当成苏冰产品 identity；正式版本仍由 `formula_version=subing_ths_15m_v1` 冻结。

### 6.2 V1 工程参数

在没有同花顺逐 Bar seed 证据前，V1 工程计算固定为当前仓库可复算、Web-compatible 的通用 MACD 口径：

```text
fast             = 12
slow             = 26
signal           = 9
ema_seed_policy  = sma_window
histogram_scale  = 2
round_digits     = 6
sma_period       = 21
```

说明：

- `histogram_scale=2` 只影响 MACD 柱，不影响 DIFF/DEA CROSS；
- 用户提供的公式没有定义历史序列第一根 EMA 的初始化细节；
- 本 Spec 不声称 `sma_window` 是同花顺内部 seed；
- 对外只声明“按用户公式 clean-room 实现，并在真实通知启用前通过同花顺样本兼容性验收”。

如果真实样本证明 seed 导致正式 Candidate 稳定差异：

```text
BLOCK activation
→ 修订设计
→ 新 formula_version
```

不得静默覆盖 V1 历史语义。

---

## 7. 数据身份、warm-up 与因果边界

正式决策输入：

```text
series_kind = actual_dominant
frequency   = 15m
bar_status  = completed
```

主力身份只认 `MainContractMap rank=1`。

不得使用 continuous 替代 actual_dominant、次主力、未完成 Bar、preview Bar、其他周期 fallback、自判主力或文件 glob。

Historical 读取必须通过 `MarketDataService` / 既有 typed Market read seam。

### 7.1 物理合约隔离

Candidate 决策 Bar 必须属于当前 rank1 物理合约，指标递归状态不得跨物理合约继承。

为了避免主力切换后等待数十根 15m 才重新 ready，允许使用“当前 rank1 物理合约自身的 pre-dominant 历史”只做 numeric warm-up，但必须满足：

- 只读取同一 physical contract；
- warm-up Bar 严格早于当前决策 Bar；
- 不使用未来 Bar；
- pre-dominant Bar 本身不能生成 Candidate / Event；
- 不跨合约拼接 EMA/MACD/SMA state；
- 数据仍经 MarketDataService / Catalog 身份读取。

如果同一物理合约历史不足以使 MACD/SMA ready，则返回 `warming_up`，不猜测、不跨合约补齐。

---

## 8. Alert Rule 与 Evaluator Registry

当前 `develop` 的 Alert Runtime 仍是单 HTDY evaluator 构造，同时 DB Rule 循环会复用该 evaluator。新增第二条 Rule 后必须收敛为：

```text
rule_code
→ AlertRuleDefinition
→ evaluator
→ notification policy
```

稳定映射：

```text
htdy_original_15m
→ HtdyOriginalEvaluator
→ HTDY formatter

subing_ths_alert_15m_v1
→ SubingThs15mEvaluator
→ SuBing formatter
```

要求：

- evaluator 必须由 `rule_code` 精确选择；
- unknown DB Rule：startup fail-closed；
- missing evaluator / formatter：startup fail-closed；
- 一个 Rule 不能误用另一个 Rule 的 evaluator 或 formatter；
- HTDY 现有 repaint / first-seen 语义保持不变；
- SuBing THS 是 non-repainting current-completed-bar observation，不需要 HTDY repaint scan。

### 8.1 SuBing evaluator 输入输出

只接受：

```text
actual_dominant
15m
current completed Bar == trigger Bar
current contract == rank1 contract
sufficient same-contract warm-up
```

输出只能是：

```text
()
("buy",)
("sell",)
```

---

## 9. Live Runtime

不新增第二个 Alert 进程、scheduler、队列或 worker。

复用当前单进程 Alert Runtime：

```text
Market Runtime
→ completed Live Bar Pub/Sub
→ Alert Runtime
→ enabled DB Rules
→ scope check
→ evaluator registry
→ AlertEvent
→ notification policy
→ one-shot PushPlus
```

苏冰只消费 15m completed Live trigger，不响应 1m/5m/30m/60m、`canonical_updated`、startup drain、repair、replay 或 after-market recalculation。

### 9.1 Startup / restart

启动或重启可以读取历史 warm-up，但：

```text
restore/catch-up != Event creation
restore/catch-up != PushPlus
```

只有 Runtime 正常运行期间新到达、经过正式校验的自然 completed 15m trigger 才允许产生新苏冰 Event。

Runtime 离线期间已经完成的历史 Bar 不补 Event、不补通知。

---

## 10. Rule 与 Scope

0043 后通用 Rule schema 已收敛为：

```text
rule_code
enabled
scope_product_frequencies
```

新苏冰必须复用该结构，禁止恢复：

```text
scope_products
action_id
strategy_payload
```

### 10.1 正式 Scope

产品目标：

```text
current operational_products × 15m
```

实际有效集合：

```text
operational_products ∩ Rule.scope_product_frequencies
```

`operational_products.txt` 是 Runtime authorization；Rule Scope 是通知授权，不能合并。

### 10.2 Migration 初始状态

0044 不能把某一天的 60 品种硬编码成永久数据库事实，只创建：

```text
rule_code = subing_ths_alert_15m_v1
enabled = false
scope_product_frequencies = {}
```

### 10.3 首次全量激活

后续独立 production Scope Gate 必须原子完成：

1. 只读加载当时最新 `operational_products.txt`；
2. 生成精确 `symbol -> ["15m"]`；
3. 在一个 DB transaction 内替换完整 Scope 并将 Rule enabled 设为 true；
4. commit 后重新只读校验 Scope 与 operational universe 完全一致。

不允许用 60 个独立、可能留下半完成状态的手工 HTTP 调用完成首次全量激活。

实现可增加一个窄范围、可 dry-run 的 runtime administration seam；不得建设通用 workflow 平台。

---

## 11. AlertEvent 合同

复用当前 `alert_events`，不新增表。

正式字段：

```text
rule_id
symbol
contract
trading_day
frequency = 15m
bar_end
result_codes = ["buy"] | ["sell"]
detected_at
notification_attempted_at
created_at
```

唯一业务身份继续为：

```text
rule_id × symbol × frequency × bar_end
```

同一 identity：

- facts 完全一致：no-op；
- contract / trading_day / result_codes 冲突：fail-closed；
- 不改写原 Event；
- 不重发通知。

必须保持：

```text
Event commit first
→ transport attempt at most once
```

`notification_attempted_at` 表示首次处理 pass 已进入 one-shot 通知尝试路径，不表示 provider accepted，更不表示微信实际送达。

---

## 12. PushPlus 与消息文案

V1 继续复用当前 PushPlus transport，不新增 provider client。

### 12.1 Notification policy 不得再写死 HTDY

当前 dispatcher 的标题、formatter 和 observers audience 仍是 HTDY 专用。新增第二 Rule 后必须由第 8 节的 rule notification policy 决定：

```text
rule_code → title / formatter / audience
```

不得通过 `if unknown then HTDY` fallback。

### 12.2 Audience

苏冰 V1 与 HTDY 使用同一个现有观察者 Topic，以避免第二套 token、成员数据库和配置文件迁移。

当前私有配置键 `htdy_topic` 可以作为 legacy-named shared observers topic 继续读取；V1 不要求仅为重命名而修改 Git-external 配置。

系统不读取 Topic 成员清单，也不声明精确送达人数。

未来如需 HTDY 与苏冰不同 audience，必须单独版本化配置合同。

### 12.3 文案

多头：

```text
【苏冰预警】RB 螺纹钢

15m 多头预警

触发：
MACD 金叉
收盘价位于 MA21 上方

当前主力：RBxxxx
信号K线：2026-09-02 10:45

请打开归一量化图表复核。
研究观察，非交易指令
```

空头：

```text
【苏冰预警】RB 螺纹钢

15m 空头预警

触发：
MACD 死叉
收盘价位于 MA21 下方

当前主力：RBxxxx
信号K线：2026-09-02 10:45

请打开归一量化图表复核。
研究观察，非交易指令
```

禁止在 V1 消息加入评分、胜率、60m/D1、Range、ATR、零轴距离、量能/OI、目标价、止损或仓位。

保持：

```text
no retry
no queue
no outbox
no fallback
no replay
no backfill
```

transport 失败时 Event 保留、Runtime health 记录失败、Web 仍显示 Event，不自动补发。

---

## 13. 最小可靠性可见性

V1 不恢复旧 Boundary Ledger，也不新增 `alert:watch-runtime-status`。

仅靠全局 Alert heartbeat 又不足以证明苏冰 15m evaluator 在推进，因此在现有 `alert:runtime-status` 增加 bounded 的 per-rule projection。

目标 schema v6：

```text
rule_status: {
  "htdy_original_15m": {
    "last_evaluated_bar_at": ...,
    "last_event_at": ...,
    "last_failure_at": ...,
    "error_type": ...
  },
  "subing_ths_alert_15m_v1": {
    "last_evaluated_bar_at": ...,
    "last_event_at": ...,
    "last_failure_at": ...,
    "error_type": ...
  }
}
```

约束：

- 固定 Rule key，不保留 symbol 级无限历史；
- 不新增 PostgreSQL health 表；
- 不新增第二 Redis status key；
- 不统计收益、胜率或策略状态；
- SuBing `last_evaluated_bar_at` 只有完成 scope + input + evaluator 全流程后才能推进；
- warm-up / input / evaluator 失败不能冒充正常评估。

该字段只回答“最近的苏冰 15m 处理是否真正进入 evaluator”，不是旧 Boundary Ledger 的变体。

---

## 14. Alert API

当前 API/schema 中仍存在 HTDY-only DTO 和 `Literal["htdy_original_15m"]`。新增第二条 active Rule 后必须泛化现有 API，而不是复制第二套接口。

继续复用：

```text
GET /api/alerts/products/{symbol}
PUT /api/alerts/rules/{rule_code}/scope/{symbol}/{frequency}
GET /api/alerts/events
GET /api/alerts/current-events
GET /api/alerts/products/{symbol}/current-events
```

正式 `rule_code` union：

```text
htdy_original_15m
subing_ths_alert_15m_v1
```

要求：

- `/events` 按真实查询 Rule 返回；
- serializer 不得把全部 Event 强制写成 HTDY；
- current-events 可以同时返回两条 Rule；
- unknown Rule 继续 fail-closed / 404；
- HTDY wire 行为非回归。

不新增 `/api/subing/*` 顶级 API。

---

## 15. Market Web

不新增顶级 route，仍使用：

```text
/market
/market/chart
```

Web 只消费 typed Market / Alert API，不计算正式苏冰公式。

### 15.1 `/market`

新增紧凑“最新苏冰预警”区域，目标 10–20 条：

```text
10:45  RB  多头预警
10:30  AG  空头预警
10:15  JM  多头预警
```

至少显示时间、品种、多/空、15m 和图表入口。

数据从全局 `current-events` 一次读取后按 `rule_code=subing_ths_alert_15m_v1` 投影，禁止 60 次逐品种请求。

若 Market 首页同时进行独立重构，苏冰区域只能作为现有 Alert facts 的小组件接入，不创建第二套首页数据模型。

### 15.2 `/market/chart`

正式 Event marker：

```text
S↑  多头预警
S↓  空头预警
```

Marker 必须来自 AlertEvent。Web 不允许通过 MACD/SMA 自己创建正式 marker。

Tooltip：

```text
苏冰预警
15m 多头预警
MACD 金叉
Close > MA21 (SMA21)
2026-09-02 10:45
RBxxxx
```

HTDY 与苏冰 marker tone 必须区分。

### 15.3 MA21 图线

V1 不强制新增 SMA21 主图线。

本轮用户要求是“信号 Push + Web 显示”；正式价值先由 Event list + marker + deep link 完成。若后续需要可视化 `MA21 (SMA)`，作为通用只读指标单独实现，不能成为第二 Candidate authority。

---

## 16. Migration 0044

新 migration：

```text
20260902_0044_subing_ths_alert.py
```

`down_revision = 20260902_0043`。

0044 只做：

1. preflight 当前 DB 正好处于 0043 后结构；
2. 验证只有 `htdy_original_15m` Rule；
3. 验证 HTDY Rule/Event 不被修改；
4. 插入 `subing_ths_alert_15m_v1`；
5. 新 Rule `enabled=false`；
6. 新 Rule `scope_product_frequencies={}`；
7. postflight 验证恰好两条 Rule。

0044 不新增表、列、`scope_products`、`action_id`、`strategy_payload`，不自动激活 Scope，不发送通知。

`downgrade()`：unsupported / fail-closed。

### 16.1 0042 → 0044 production cutover

production 可能仍处于 0042，因此 0043 + 0044 是一个 forward-only schema cutover 链。

新应用代码只承诺 0044 后 active schema，不建立旧策略 compatibility reader。

正式 cutover：

```text
release main/tag
→ 准备 exact-tag Runtime root（不启用）
→ Runtime maintenance Gate：停止受影响服务
→ DB Gate：一次受控 upgrade 0042 → 0044 + readback
→ Runtime promotion Gate：切 exact approved tag
→ health / smoke
→ Scope activation Gate：原子设置 operational × 15m + enable
→ 自然 completed 15m evidence
```

### 16.2 中途失败

0043 是 forward-only 且不支持 downgrade，因此必须显式处理：

- 若 0043 前失败：DB 保持 0042，服务保持停止，按原生产事实处置；
- 若 0043 已成功而 0044 失败：DB 处于 HTDY-only 安全状态，**不得 downgrade、不得恢复旧苏冰 Rule/Event、不得启动旧 Runtime**；
- 此时保持受影响服务停止，记录 exact Alembic head 和失败原因；
- 只能通过审查后的 forward fix / 重新执行尚未成功的 0044 路径恢复到新 active schema；任何 retry 都需要新的明确 DB 执行授权；
- 只有 0044 postflight 完成后才能进入新 Runtime promotion。

每个外部 Gate 都必须得到当次明确授权；上一 Gate 成功不自动授权下一 Gate。

---

## 17. 错误与 fail-closed

以下情况不得创建 SuBing Event：

- Rule disabled；
- symbol 不在 operational universe；
- symbol/frequency 不在 Rule Scope；
- frequency 不是 15m；
- Bar 未 completed；
- actual_dominant 身份不可证明；
- rank1 contract 不匹配；
- warm-up 不足；
- SMA/MACD invalid；
- evaluator mapping 缺失；
- Event facts 冲突。

Event 已持久化后，taxonomy / formatter / transport / provider acceptance 失败不得删除 Event；记录 Runtime failure、Web 继续显示、不自动 retry。

---

## 18. 安全与授权

本 Spec 和普通 implementation 不授权：

- production PostgreSQL / Redis mutation；
- production Scope；
- Git-external notification config 修改；
- 真实 PushPlus；
- Runtime enable/switch/promotion；
- main merge；
- tag；
- GitHub Release。

这些按 `AGENTS.md` 逐项获取单次明确执行意图。

不得读取、输出或提交 token、Topic code、provider reference 或内部凭据。

`auto_order=false` 全程不变。

---

## 19. 测试合同

### 19.1 Formula / Kernel

必须覆盖：

- SMA21 arithmetic mean；
- EMA12 / EMA26 / DEA9；
- histogram scale 2；
- golden/dead cross；
- equality edge；
- `close == SMA21`；
- warming / invalid；
- batch-incremental parity；
- prefix invariance；
- future-tail invariance；
- deterministic six-decimal projection；
- Kernel 是唯一 Candidate authority。

### 19.2 Physical contract / data

必须覆盖：

- rank1 identity；
- pre-dominant same-contract warm-up only；
- no cross-contract warm-up；
- rollover reset；
- incomplete/preview rejected；
- wrong contract rejected；
- MDS / mapping unavailable fail-closed。

### 19.3 Alert Runtime

必须覆盖：

- rule-code evaluator dispatch；
- rule-code formatter dispatch；
- HTDY evaluator/formatter 非回归；
- SuBing 只消费 15m；
- SuBing 不消费 `canonical_updated`；
- startup drain 不建 Event；
- Scope disabled no-op；
- operational guard；
- Event first；
- duplicate facts no-op；
- conflict fail-closed；
- transport at most once；
- transport failure 不删 Event；
- per-rule status；
- unknown DB Rule / registry mismatch startup fail-closed。

### 19.4 API

必须覆盖两条 Rule projection、真实 rule_code serializer、SuBing `/events`、混合 `/current-events`、product current-events、invalid Rule 和 HTDY wire non-regression。

### 19.5 Web

必须覆盖 latest SuBing list、无 O(N) 请求、`S↑/S↓`、HTDY/SuBing tone、deep link、formal `bar_end` identity、Web 无 BUY/SELL 公式实现、mobile/desktop 基本布局和 `/market/chart` 非回归。

### 19.6 Migration

isolated disposable PostgreSQL 必须覆盖：

```text
0042 → 0043 → 0044
```

验证 legacy SuBing 删除、strategy columns 删除、HTDY 完整保留、0044 新 Rule disabled+empty scope、恰好两条 active-schema Rule、unexpected state fail-closed、downgrade rejected，并覆盖“0043 后 0044 失败时保持 HTDY-only，不恢复旧苏冰”的 forward-only 行为。

---

## 20. 同花顺兼容性验收 Gate

代码合入 `develop` 不等于“与同花顺一致”。

真实通知激活前必须取得用户可核验的同花顺期货通 15m 样本。

最低验收：

- 至少 2 个品种；
- 至少 5 个金叉预警；
- 至少 5 个死叉预警；
- 核对 direction、completed 15m Bar 时间、CROSS、Close 相对 MA21、主力合约身份。

无法导出逐 Bar 指标值时可以用截图/时间点人工核验，但必须记录来源与判断依据。

差异优先检查 seed、Bar 时间和物理合约 warm-up，不得先改公式。

未通过：可以保留代码/Web shadow，但不得启用真实 SuBing Rule，不得发送真实 SuBing PushPlus。

---

## 21. 完成定义

`CODE_COMPLETE`：实现、测试、migration code、Web、canonical sync 完成。

`TEST_COMPLETE`：完成 targeted/full backend、isolated PostgreSQL、Ruff、Mypy、Web unit、Playwright、Web build、OpenSpec、canonical consistency、secret scan 和 `git diff --check`。

`RELEASED`：独立 release Gate 后 `main + annotated tag + GitHub Release + API/Web version` 一致。

`RUNTIME_READY`：exact-tag Runtime promotion + 自然 completed Live evidence 通过。

`BUSINESS_CLOSED` 至少还要求：

- 0044 production migration 完成；
- SuBing Scope 原子激活为当时 operational universe × 15m；
- Rule enabled；
- 自然 completed 15m 经 SuBing evaluator；
- 至少一条自然 SuBing Event 持久化；
- one-shot transport 发生；
- provider acceptance 如有只记录为 provider acceptance；
- 用户人工确认至少一次实际微信收到；
- Web 同一 Event 可见并可打开图表复核。

---

## 22. 外部 Gate

固定顺序：

```text
G0  Spec 批准
G1  Implementation Plan 批准
G2  Code + tests + independent Review
G3  允许集成 develop
G4  Release candidate
G5  release main/tag
G6  Runtime maintenance stop
G7  production DB 0042→0044
G8  exact-tag Runtime promotion
G9  production Scope activation + Rule enable
G10 同花顺兼容性 evidence
G11 自然 15m Event / one-shot transport
G12 用户人工微信送达确认
```

执行时已由真实 evidence 完成的 Gate 可以跳过重复动作，但历史授权不能替代任何新的 mutation 授权。

---

## 23. 推荐实现拆分

后续 Implementation Plan 只拆五个 Packet：

```text
S1 Formula Kernel
   SMA21 + SubingThs15mKernel + same-contract warm-up + golden tests

S2 Alert Runtime
   rule evaluator registry + notification policy + Event + per-rule health

S3 API / Web
   generic Alert DTO + recent alerts + S↑/S↓ + deep link

S4 Migration / Scope activation seam
   0044 + isolated PostgreSQL + atomic operational×15m activation

S5 Canonical / Full Verification / RC
   PROJECT_SOURCE / DECISIONS / ARCHITECTURE / TESTING / OpenSpec
   + full verification + independent exact-head Review
```

每个 Packet 独立 task branch/worktree/PR；不得在一个实现会话中一路做到 release 或 Runtime。

---

## 24. 禁止范围

V1 明确禁止：

```text
恢复 subing_strategy_v1
恢复 Daily Watch / Factor / Lifecycle / Action / Episode
恢复 Strategy Runtime / Strategy Scope
零轴 / Range / 量能 / OI / ATR / 斜率 / 多周期过滤
评分 / 胜率 / 回测收益
持仓 / OPEN / CLOSE / 止盈止损 / 目标价 / 加减仓
自动下单
retry / queue / outbox / fallback / replay / backfill
generic strategy framework
第二个 Alert Runtime
第二套 Market data reader
Web 复制正式公式
```

---

## 25. Spec 自审与修正

提交前按产品、公式、因果、Alert、迁移、Runtime、Web 和授权八个方向反向 Review。

已关闭 finding：

1. **旧 Watch 可能被误认为 active authority**：改为 #307 + 新身份，旧 #286 只留历史语义。
2. **当前 Runtime 单 HTDY evaluator 会把第二 Rule 送进错误 evaluator**：冻结 `rule_code → evaluator` registry。
3. **当前 dispatcher 的标题/formatter/audience 写死 HTDY**：冻结 `rule_code → notification policy`，missing policy fail-closed。
4. **当前 API DTO/serializer 写死 HTDY rule_code**：复用现有 API，但泛化为两条明确 Rule union，禁止第二套 SuBing API。
5. **旧 Watch migration 会逆向恢复 0043 已删除字段**：0044 只插 Rule，不加表列。
6. **migration 硬编码当前 60 品种会污染长期事实**：0044 disabled + empty scope；首次 activation 原子读取当时 operational universe。
7. **新代码与 0042/0043/0044 长时间混跑会发生 ORM/Rule composition 冲突**：不建 compatibility reader，采用 maintenance stop → DB → exact-tag Runtime。
8. **0043 成功而 0044 失败无法 downgrade**：明确保持 HTDY-only、服务停止、只允许 forward fix，retry 需新授权。
9. **为解决漏推再次建设 Boundary Ledger**：只增加 bounded per-rule last-evaluated 状态，不增加新 Redis key/PG history。
10. **PushPlus 为苏冰新增第二 Topic 配置会扩大私有配置面**：V1 复用现有 observers Topic；未来不同 audience 单独版本化。
11. **Web 为复核复制 SMA/MACD 公式**：正式 marker 只读 Event，V1 不强制新增 SMA21 图线。
12. **直接声称同花顺逐 Bar 完全一致但 source formula 没给 seed**：工程 seed 固定、对外不夸大，真实通知前增加 source compatibility Gate。
13. **通用 MACD primitive 版本名不应冒充产品 identity**：新增 `SubingThs15mKernel` 封装正式 formula identity，底层 primitive 只是数学依赖。

Placeholder、未决产品选择和需要实现者自行猜测的核心语义：0。

自审结论：本 Spec 已足够进入用户 written-Spec Review；不需要为 V1 再扩张架构。

---

## 26. 用户 Review 决策点

本 Spec 已冻结：

- 新身份 `subing_ths_alert_15m_v1`；
- completed actual_dominant 15m only；
- MACD CROSS + SMA21 是唯一 Gate；
- `SubingThs15mKernel` 是唯一公式 authority；
- 复用 0043 后通用 Alert schema；
- 稳定生产 Rule 为 HTDY + 新苏冰；
- 0044 新 Rule disabled + empty scope；
- 首次激活原子同步 operational universe × 15m；
- 苏冰与 HTDY 共用现有观察者 Topic；
- Web 只做 recent Event + S↑/S↓ marker + deep link；
- 不恢复旧策略域；
- 不建设 Boundary Ledger / queue / retry；
- 真实通知前必须经过同花顺兼容性 evidence Gate。

用户批准本 written Spec 后，下一步才允许编写 Implementation Plan。

本 Spec 本身不授权源码实现、production migration、Scope mutation、真实通知、Runtime promotion、main/tag/Release 操作。
