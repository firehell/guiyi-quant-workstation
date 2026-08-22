# Market Trend Focus V1 设计规格

更新时间：2026-08-23

> 状态：设计完成，尚未实现。本文是当前实现任务的 exact 设计依据，不代表 production 已具备该能力；当前 release、Runtime、Alert Scope 与 pending Gate 仍只看 `STATUS.md`。实现验收完成后，应把仍需长期维护的稳定业务语义收敛进 active canonical，并删除本任务临时文档，由 Git history 保留过程。

## 1. 目标

`market_trend_focus_v1` 是现有 Market Web B1「优先检查」的算法升级，不是新 Strategy/Signal 平台。

它只解决一个问题：

> 从 active 60 中持续压缩出少数值得人工检查的顺势趋势机会，并明确展示当前阶段、下一条件与失效条件，减少全市场机械盯盘，同时尽量不漏掉真正的趋势启动。

核心链路固定为：

```text
active 60
→ D1 热点事实
→ D1 SMA21 方向
→ 60m SMA21 环境
→ 15m causal Swing / Range 生命周期
→ 5m causal Swing + Volume 最终择时
→ 人工重点检查
→ RUNNING / WEAKENING 趋势跟踪
```

所有结果始终只是观察事实，不是交易指令；`auto_order=false` 不变。

## 2. 设计原则

1. **升级现有 B1 Focus，不新建平台**：保留首页“需要处理 → 优先检查 → 全市场研究”，只替换旧 `selectMarketFocus()` 的核心选择逻辑。
2. **一个问题一个主要机制**：热点只看价格/成交量/波动；方向只看 SMA21；结构只看 causal Swing/Range；力度只看 Volume。
3. **纯只读、可重算**：不新增 PostgreSQL 表、Redis lifecycle state、worker、scheduler、Runtime label。
4. **completed-bar only**：未完成 5m/15m/60m/D1 Bar 不得改变正式状态。
5. **physical-contract safe**：60m/15m/5m 只使用当前 rank1 的 exact physical contract，不跨合约延续 Pivot、Range 或 lifecycle。
6. **causal / prefix-invariant**：任何 Pivot 只有在 `confirmed_at` 才成为可用事实；追加未来 Bar 不得改变过去已经输出的状态事实。
7. **无综合分**：排序采用显式字典序，不用加权 score。
8. **不复用 offline Research reducer 作为 Runtime 依赖**：可以参考 N Structure 的因果设计，但不得让 Market/Runtime import `app.research`，也不建立 Generic Strategy/Opportunity Framework。
9. **YAGNI**：V1 不做盘中热点旁路、Alert、历史全量 Overlay、独立 CLI、Candidate Validation/OOS Framework、AI 解释。

## 3. 非目标

V1 明确不实现：

- 自动交易、账户连接、订单/委托/持仓管理；
- 仓位推荐、止损手数、PnL/胜率/收益预测；
- 综合机会评分、Candidate winner/rank；
- Open Interest、MACD、BOLL 参与 Trend Focus 硬判断；
- SuBing/N/JDJ/HTDY/主力照妖镜给 Trend Focus 投票或确认；
- 新 Alert Rule、PushPlus 推送、通知 retry/queue/replay；
- 新数据库表、新 Redis key/domain、新 Runtime 进程；
- 新 Research CLI、report/evidence framework；
- 历史 K 线全量 Trend Focus Overlay；
- 自动后台轮询/定时扫描。V1 只在页面加载或用户刷新时读取当前快照。

## 4. 工程位置

长期实现应尽量收敛为一个 Market read-model 模块：

```text
services/quant-api/app/market_data/market_trend_focus.py
```

该模块可以同时承载：

- exact 常量；
- dataclass / enum；
- SMA21 判定；
- 本功能私有的 causal Swing reducer；
- Range / lifecycle reducer；
- snapshot 组装与 deterministic sort。

除非实现时文件已经出现明显职责失控，否则不得预先拆成 `policy/state/swing/pattern/service/validation/report` 一整套文件。

接入只允许修改现有：

```text
services/quant-api/app/api/market.py
services/quant-api/app/schemas/market.py
services/quant-api/app/market_data/composition.py   # 仅在现有 builder 复用需要时最小修改
apps/quant-web/src/api/market.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/components/market/MarketFocusList.vue
apps/quant-web/src/pages/market/index.vue           # 仅在数据加载/刷新需要时最小修改
```

不得新建 `TrendFocusService/Repository/Manager/Runtime/Store` 等长期抽象，除非现有 composition 无法直接承载并且 Review 明确认可。

## 5. 数据入口与身份

### 5.1 Historical / Live 边界

- Historical 仍只经 `MarketDataService`。
- 当前盘中 completed Live observation 仍只经 `MarketReadService`。
- Trend Focus 不直接读 Parquet、Redis、RQData 或 MainContractMap。
- Live 不写回 Canonical，不创建 Trend Focus persistence。

### 5.2 D1 identity

D1 热点与方向使用当前既有 Radar / `actual_dominant` completed D1 事实。

热点直接复用现有 Radar exact metrics：

- `price_change_1d`
- `volume_ratio20`
- `atr14_percentile252`

D1 SMA21 使用 completed `actual_dominant` 日线。

### 5.3 60m / 15m / 5m identity

先由现有主力解析得到当前 rank1 `physical_contract`，然后 60m、15m、5m 全部使用：

```text
series_kind = contract
contract = current rank1 physical contract
```

允许读取该真实合约在成为主力之前已经存在的 completed Historical Bars 作为 warm-up；禁止把上一主力合约的 Pivot/Range/lifecycle 延续到新合约。

current physical contract 变化时，旧 lifecycle 立即失去当前身份；新合约从自己的 Bars 重新计算。

### 5.4 当前快照合并

对于当前 physical contract：

```text
Historical contract Bars
+
MarketReadService 当前 completed Live/Post-close Bars
→ 按 bar_end 去重、升序
```

盘中 `trading/break` 时如果 Live identity/contract 无法唯一解析或 Live 不可用，该 symbol 当前 intraday Trend Focus 必须 unavailable，不得静默退回 stale Historical。

闭市时可以使用最新 completed Historical，并在 MarketReadService 存在 post-close snapshot 时合并。

## 6. D1 热点门槛

三个热点条件沿用现有 Radar exact 阈值：

```text
price_hot  = abs(price_change_1d) >= 0.02
volume_hot = volume_ratio20 >= 1.50
vol_hot    = atr14_percentile252 >= 0.80
```

`volume_ratio20` 的分母为当前日之前 20 个 completed D1 的平均成交量；ATR 分位沿用当前 Radar 既有实现。

三项 metric 任一为 `None` 时，该 symbol 对“新机会 admission”视为 unavailable，不允许把缺失值当作 false 后仍凑够 2/3。

```text
hot_count >= 2
→ current_hot = true
```

热点只是**新机会 admission / 排序事实**，不是趋势跟踪的持续退出条件。

V1 不实现盘中 `INTRADAY_BREAKOUT_OVERRIDE`；如果 shadow 证明 D1 热点门槛大量漏掉真实趋势，再单独设计。

## 7. SMA21 exact 定义

`MA21` 在本规格中精确定义为 **Simple Moving Average**：最近 21 根 completed Close 的算术平均值。

```text
SMA21[t] = mean(Close[t-20 ... t])
```

为了判定连续三根 SMA 方向，D1 和 60m 至少需要 23 根同 identity completed Bars。

### 7.1 D1 方向

```text
LONG:
Close[t] > SMA21[t]
AND
SMA21[t] > SMA21[t-1] > SMA21[t-2]

SHORT:
Close[t] < SMA21[t]
AND
SMA21[t] < SMA21[t-1] < SMA21[t-2]

其他:
NEUTRAL
```

D1 `NEUTRAL` 不产生新的 Trend Focus 机会。V1 是 stateless current read model；如果 D1 变成 NEUTRAL，symbol 不继续出现在当前 Trend Focus 中，但这不等价于真实持仓平仓指令。

### 7.2 60m 环境

以 D1 LONG 为例：

```text
CONTINUATION:
Close > SMA21
AND SMA21 连续 3 根上升

REVERSAL_BLOCK:
Close < SMA21
AND SMA21 连续 3 根下降

PULLBACK:
其余状态
```

D1 SHORT 完全镜像。

`CONTINUATION` 与 `PULLBACK` 都允许继续评估顺 D1 方向的 15m lifecycle；`REVERSAL_BLOCK` 阻断该方向当前机会并移出当前 Trend Focus。

## 8. D1 / 60m Volume support

质量事实：

```text
current completed Volume >= previous completed Volume
→ volume_support = true
```

只用于展示与同阶段排序，不改变方向或 lifecycle。

V1 不使用 1w Volume。

## 9. 本功能私有 causal Swing

15m 和 5m 使用同一个本功能私有 causal Swing reducer；不导入 offline N Structure reducer。

每个 Pivot 包含：

```text
kind = HIGH | LOW
pivot_time
confirmed_at
price
physical_contract
epoch
```

必须满足：

```text
pivot_time < confirmed_at
```

### 9.1 顺序 reducer

从同一 physical contract 的 completed Bars 升序处理。

状态：

```text
UNRESOLVED | UP | DOWN
```

规则：

1. 若 `current.high > previous.high` 且 `current.low < previous.low`，这是 outside bar：
   - `epoch += 1`
   - 当前 swing leg 归零为 `UNRESOLVED`
   - `running_extreme = None`
   - 新 Range 只能使用当前 epoch 后确认的 Pivot。
2. `UNRESOLVED`：
   - `current.high > previous.high` 且 `current.low >= previous.low` → `UP`；
   - `current.low < previous.low` 且 `current.high <= previous.high` → `DOWN`；
   - inside/equal 情况不确认新方向。
3. `UP`：
   - `current.low >= previous.low` 时继续 UP，并在 `current.high` 创新高时更新 `running_extreme`；
   - `current.low < previous.low` 时，把 `running_extreme` 确认为 HIGH，`confirmed_at=current.bar_end`，随后切换为 DOWN。
4. `DOWN` 镜像：
   - `current.high <= previous.high` 时继续 DOWN，并在 `current.low` 创新低时更新 `running_extreme`；
   - `current.high > previous.high` 时确认 LOW，并切换为 UP。

不得用未来 Bar 回标“当时已知”的状态。UI 如果未来展示 Pivot，必须区分 `pivot_time` 与 `confirmed_at`。

## 10. 15m Range / SETUP

没有 active lifecycle 时，只在当前 epoch 的最近 confirmed Pivot 中寻找最新一个合法四 Pivot 组合。

合法序列只能是：

```text
H1 → L1 → H2 → L2
```

或：

```text
L1 → H1 → L2 → H2
```

且必须：

```text
H2 <= H1
L2 >= L1
```

成立后：

```text
range_upper = max(H1, H2)
range_lower = min(L1, L2)
stage = SETUP
```

一旦 SETUP 成立，本轮 lifecycle 的 `range_upper/range_lower` 冻结，不因后续区间内 Pivot 自动移动。

在 LONG context 中，如果 SETUP 尚未突破且 completed 15m Close < `range_lower`，本轮 SETUP 失效；SHORT 镜像为 Close > `range_upper`。失效后只有在失效 boundary 之后新确认的 Pivot 才能形成新的 SETUP，禁止立即复用原四 Pivot 重启同一 Range。

## 11. 15m 六阶段 lifecycle

公开 stage 精确只有：

```text
SETUP
BREAKOUT
RETEST
READY
RUNNING
WEAKENING
```

不长期公开 `FALSE_BREAKOUT / ENDED / ACTIONABLE` 等额外 stage；相关事实由字段或从当前列表移除表达。

### 11.1 SETUP → BREAKOUT

LONG：

```text
completed 15m Close > range_upper
```

SHORT：

```text
completed 15m Close < range_lower
```

仅 High/Low 影线刺破不算正式突破。

进入：

```text
stage = BREAKOUT
breakout_at = trigger_bar.bar_end
confirmation_count = 0
```

### 11.2 BREAKOUT 三 Bar 确认

首次突破 Bar 不计入 3 根确认。

LONG 从下一根 completed 15m 开始：

```text
Close > range_upper
→ confirmation_count += 1
```

任意一根：

```text
Close <= range_upper
→ 本轮 lifecycle 失效
```

SHORT 镜像。

连续三根成功后：

```text
stage = RETEST
confirmation_count = 3
breakout_confirmed_at = 第3根确认Bar.bar_end
retest_held = false
```

失效后，只有失效 boundary 之后新确认的 Pivot 才能建立下一 SETUP。

### 11.3 RETEST

突破确认后，原 Range 边界成为硬失效线：

LONG：

```text
任意 completed 15m Close <= range_upper
→ lifecycle 失效
```

SHORT 镜像。

影线进入原区间但收盘仍在突破侧允许继续。

LONG 的 causal retest 需要：

1. `breakout_at` 之后出现一个 confirmed 15m HIGH；
2. 随后出现 confirmed 15m LOW；
3. 到 LOW 的 `confirmed_at` 为止，所有正式 Close 均未触发原 Range 失效线。

此时：

```text
retest_held = true
retest_pivot = 该 LOW
rebreak_reference = preceding HIGH.price
```

SHORT 使用 confirmed LOW → confirmed HIGH，并以 preceding LOW 作为 `rebreak_reference`。

### 11.4 RETEST → READY（二次确认）

LONG：

```text
retest_held = true
AND
later completed 15m Close > rebreak_reference
```

SHORT 镜像。

触发 Bar 必须严格晚于 retest Pivot 的 `confirmed_at`。

进入：

```text
stage = READY
ready_at = trigger_bar.bar_end
ready_invalidation = retest_pivot.price
volume_confirmed = (
    current_15m_volume >= previous_15m_volume * 2
)
five_minute_confirmed = false
entry_confirmed_at = null
```

`volume_confirmed` 只是质量事实；即使 false，READY 结构仍成立。

READY 期间，如果 LONG completed 15m Close < `ready_invalidation`（SHORT 镜像为 >），本轮 READY 失败并结束 lifecycle；原 Range 边界失效条件仍同时有效。

## 12. 5m 最终择时

5m 只负责回答“15m READY 之后是否出现更小周期的同向 causal 再突破”，不建立第二套完整 Range lifecycle。

### 12.1 5m reference

LONG：

- 只使用 `ready_at` 之后 `pivot_time > ready_at` 且 `confirmed_at > ready_at` 的 confirmed 5m HIGH；
- 取当前 entry window 中最新可用的 HIGH 作为 `entry_reference`。

SHORT 镜像为 confirmed LOW。

### 12.2 5m confirmation

LONG：

```text
trigger_bar.bar_end > entry_reference.confirmed_at
AND trigger_bar.close > entry_reference.price
AND trigger_bar.volume >= previous_completed_5m.volume * 2
```

SHORT 镜像。

成功后：

```text
five_minute_confirmed = true
entry_confirmed_at = trigger_bar.bar_end
```

该结果仍只是“重点人工检查”事实，不是 BUY/SELL。

### 12.3 entry window 关闭

为了避免 READY 长期悬挂，entry window 在以下任一条件首次发生时关闭：

1. 5m confirmation 成功；
2. 15m 在 `ready_at` 之后首次确认出顺趋势方向的 Pivot：LONG 为 HIGH，SHORT 为 LOW。

如果 1 先发生：

```text
stage = RUNNING
running_at = entry_confirmed_at
five_minute_confirmed = true
```

如果 2 先发生而 5m 未确认：

```text
stage = RUNNING
running_at = 该15m趋势方向Pivot.confirmed_at
five_minute_confirmed = false
```

这允许系统明确表达：“趋势已经进入运行，但没有给出符合 V1 规则的 5m 最终择时。”

## 13. RUNNING / WEAKENING

### 13.1 RUNNING → WEAKENING

LONG 以当前已知最新 confirmed 15m LOW（至少包含 retest LOW）作为结构防守 Pivot：

```text
completed 15m Close < latest_confirmed_swing_low.price
→ stage = WEAKENING
weakened_at = current.bar_end
```

SHORT 镜像为 Close > latest confirmed HIGH。

只看 completed Close，影线不改变正式 stage。

### 13.2 WEAKENING → RUNNING 恢复

LONG 在 `weakened_at` 之后必须按因果顺序重新形成：

```text
confirmed LOW
→ confirmed HIGH
→ later completed Close > 该 HIGH.price
```

最后的突破 Bar 必须严格晚于 HIGH `confirmed_at`。

满足后：

```text
stage = RUNNING
```

SHORT 镜像。

### 13.3 60m / D1 阻断

任何当前 stage 下：

- 60m 进入当前 D1 方向的 `REVERSAL_BLOCK` → symbol 从当前 Trend Focus 移除；
- D1 当前不再是明确 LONG/SHORT（包括 NEUTRAL）→ symbol 从当前 Trend Focus 移除。

“移除”只是当前 read model 不再关注，不是持仓平仓或自动退出指令。

## 14. current opportunities 与 running trends

Trend Focus 每次请求对 active 60 都可重算当前 D1/60m/15m lifecycle；热点条件只限制**新机会列表**。

### 14.1 新机会列表

必须同时满足：

```text
current_hot = true
D1 direction = LONG/SHORT
60m != REVERSAL_BLOCK
stage in {SETUP, BREAKOUT, RETEST, READY}
```

分别输出：

```text
long_opportunities  0..10
short_opportunities 0..10
```

没有最低数量，不凑数。

### 14.2 趋势跟踪列表

不要求 `current_hot=true`，只要求当前 D1/60m identity 仍允许：

```text
stage = RUNNING
→ running_trends

stage = WEAKENING
→ weakening_trends
```

这样趋势进入运行后，不会仅因当日热点指标降温而消失。

## 15. deterministic 排序

禁止综合分。

### 15.1 新机会

LONG/SHORT 各自排序键：

1. stage：`READY > RETEST > BREAKOUT > SETUP`；
2. READY 内：`five_minute_confirmed=true` 优先（正常情况下会立即转 RUNNING，仅作为重算边界保护）；
3. `volume_confirmed=true` 优先；
4. D1 + 60m `volume_support` true 的数量高者优先；
5. `hot_count=3` 优先于 `hot_count=2`；
6. `abs(price_change_1d)` 大者优先；
7. `volume_ratio20` 大者优先；
8. `atr14_percentile252` 大者优先；
9. `symbol` 字典序作为稳定 tie-breaker。

BREAKOUT 同阶段时，`confirmation_count` 大者优先；RETEST 同阶段时 `retest_held=true` 优先。

最后各取前 10。

### 15.2 趋势跟踪

- `WEAKENING` 独立输出，不与 RUNNING 混排；
- 各列表按最近一次 stage 变化时间倒序；
- 同时间按 symbol 字典序。

## 16. HTTP read model

V1 只新增一个 endpoint：

```text
GET /api/v1/market/research/trend-focus
```

不新增 symbol detail endpoint；点击品种继续进入现有 Product Workspace。

顶层响应至少包含：

```text
status: ready | degraded
as_of / observed_at
long_opportunities
short_opportunities
running_trends
weakening_trends
unavailable
```

每个 item 至少包含：

```text
symbol
product_name
sector
physical_contract
direction
stage
hot_conditions
hot_count
price_change_1d
volume_ratio20
atr14_percentile252
daily_volume_support
hourly_state
hourly_volume_support
range_upper
range_lower
confirmation_count
retest_held
rebreak_reference
ready_invalidation
volume_confirmed
five_minute_confirmed
entry_confirmed_at
latest_swing_high
latest_swing_low
next_level
invalidation_level
last_transition_at
```

价格、量与比率后端继续使用 `Decimal`；Web HTTP 边界按现有 Market API 习惯 normalize 为 number。

不公开内部 pivot id、epoch、policy hash 等日常 UI 不需要的诊断字段。

## 17. fail-closed

以下任一情况不得静默替代：

- Radar `freshness_state=degraded`；
- D1 三个热点 metric 任一缺失（仅影响新机会 admission）；
- D1/60m 少于 23 根 completed Bars；
- current physical contract 无法唯一解析；
- current contract 与 Live identity 不一致；
- 盘中 Live 不可用；
- 15m/5m 输入存在非严格升序、跨 physical contract 或无法解释的 identity；
- outside bar 造成当前 swing epoch reset；
- future/incomplete Bar 进入 reducer。

全局 Radar degraded 时：

```text
status = degraded
long_opportunities = []
short_opportunities = []
running_trends = []
weakening_trends = []
```

并显式返回 unavailable / freshness 信息，不沿用上一份结果冒充当前状态。

单 symbol 数据异常时，排除该 symbol 并加入 `unavailable`，其他 symbol 可继续返回。

## 18. Web B1 设计

保留现有首页结构，不新增第二套 Trend 页面。

「优先检查」改为读取 Trend Focus API，只展示三个用户任务：

```text
新的机会
├─ 多头 N
└─ 空头 N

趋势跟踪
├─ 运行 N
└─ 转弱 N
```

默认每个分组最多展示前三个 item；剩余使用“查看更多 N”在当前块内展开，不跳新页面。

每张卡默认只显示：

```text
symbol + 名称
方向
stage 中文文案
D1 方向
60m 环境
热点命中项
15m volume_confirmed
5m 是否确认
下一条件
失效条件
```

禁止展示：

- 综合分、推荐买卖、预计收益；
- Open Interest；
- MACD/BOLL 作为 Trend Focus 证据；
- 内部 epoch/pivot id；
- SuBing/N/JDJ/MFM 的“确认票数”。

旧前端 `selectMarketFocus()` 算法在新 API 接入后删除，避免两套 Focus 语义并存。

V1 不新增自动后台轮询：沿用页面加载 + 用户主动刷新。后续如果实际使用证明需要实时提醒，再单独设计 Alert/refresh cadence。

## 19. 测试与验证

公式属于高风险交易语义，测试重点放在 causal correctness，不铺跨层重复矩阵。

### 19.1 核心 unit tests 必须覆盖

- SMA21 LONG/SHORT/NEUTRAL；
- 23-Bar 下界；
- Hot 2/3 exact 阈值与 metric None fail-closed；
- 15m/5m causal Pivot 的 `pivot_time < confirmed_at`；
- outside bar epoch reset；
- 四 Pivot Range 两种序列与收敛条件；
- SETUP opposite-boundary 失效；
- completed Close 首次突破，影线刺破不算；
- 首次突破 Bar 不计入 3-Bar confirmation；
- `Close == range boundary` 的 exact 失败语义；
- Retest HIGH→LOW / LOW→HIGH causal 顺序；
- second confirmation 必须 strict-after `retest_pivot.confirmed_at`；
- `current_volume == previous_volume * 2` 必须确认成功；
- 5m Pivot/trigger 必须 strict-after `ready_at`；
- 5m trigger 与 15m trend-direction Pivot 的 entry-window 先后；
- RUNNING → WEAKENING；
- WEAKENING → RUNNING causal 恢复；
- LONG/SHORT 镜像；
- physical-contract change 不跨合约继承；
- incremental reducer 与 full replay 最终语义一致；
- prefix invariance：追加未来 Bars 不得改变过去已确认 transition 的时间与内容。

### 19.2 接入测试

只保留必要层级：

- 1 组 API contract tests：ready/degraded、Decimal 序列化、unavailable；
- Web unit：分组、前三个/查看更多、中文状态、无综合分/无 OI；
- 现有 B1 Playwright 只改 1 条关键路径，验证「优先检查」读取后端 Trend Focus 并可进入现有 Product Workspace。

不得把同一 reducer 合同在 unit/service/API/browser 重复做完整矩阵。

### 19.3 开发期真实历史只读检查

实现阶段允许使用现有 `MarketDataService` 做一次性、无仓库副作用的 Historical read-only 检查，用于确认：

- active60 的 stage 数量不是明显异常；
- FALSE breakout/reset 不形成死循环；
- READY/RUNNING 不集中到极少数产品；
- prefix/full replay 结果一致。

本任务不得因此新增永久 CLI、report framework 或版本化 profitability evidence，也不得输出 winner/PnL/Sharpe/可交易结论。

## 20. 文档与状态

本文件与实现 task 都属于当前高风险任务的临时 active 文档。

实现完成并通过独立 Review 后：

1. 将仍需长期维护的稳定业务语义收敛到最小 active canonical（优先更新既有 `PROJECT_SOURCE.md` / `docs/ARCHITECTURE.md`；只有确有长期必要时才新增独立 deep canonical）；
2. `STATUS.md` 只在实际实现/部署状态发生变化时按其职责更新，不因设计完成提前宣布 Ready；
3. 删除 `docs/tasks/2026-08-23-market-trend-focus-v1-spec.md` 与对应 implementation task，历史只由 Git history 追溯。

## 21. 人工 Gate

本设计只授权后续实现计划，不授权：

- release/main/tag；
- Runtime switch/promotion；
- Alert/PushPlus 真实通知；
- production DB/Canonical/Redis mutation；
- 订单或账户能力。

Trend Focus V1 第一版实现后先作为 Web 人工观察 read model 使用；是否增加 Alert、自动刷新 cadence、盘中热点旁路或历史 Overlay，必须基于真实使用反馈另立任务。