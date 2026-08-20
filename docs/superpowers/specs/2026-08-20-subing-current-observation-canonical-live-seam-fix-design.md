# SuBing Current Observation Canonical / Live Seam 修复规格

> 状态：Implementation Complete / Independent Review Pending
>
> 日期：2026-08-20
>
> 开发基线：`develop@139d7a9d03a2665ec53a3b10a95b76cc9437818d`
>
> 当前 production：`v1.6.3@e354ea7c9b1de782af830360ca3048bbb1afd057`
>
> 任务性质：SuBing current observation 读取接缝 bug fix。实现阶段按 Lane 3 处理，因为 `SubingReadService` 同时被 Market Web 与 `subing_entry_signal_v1` Alert Runtime 消费；本规格本身只新增文档，不授权 Runtime、release、tag、Scope、通知、DB/Canonical 写入或任何订单行为。

## 1. 结论

本次故障不是 SuBing Factor / Signal 公式失效，也不是 15m 周期不受支持，而是 **SuBing current snapshot 把 wall-clock `now` 当成 strict Historical pagination cursor**，在交易中 `Canonical edge < now` 的正常 Canonical / Live 分层状态下触发 Historical fail-closed；随后 Web 又把 SuBing snapshot 不可用错误降级成 `visibleBars=[]`，最终形成“Factor 快照不可用 + 0 bars + 空图”。

修复必须同时关闭两个问题：

```text
Backend root cause
SuBing Historical seed cursor 超过 Canonical edge
→ DATASET_OR_PARTITION_MISSING
→ /research/subing 不可用

Frontend degradation bug
subing snapshot = null / error
→ segment_start_trading_day 不存在
→ visibleBars = []
→ 已成功加载的基础 K 线被一并隐藏
```

修复的核心原则是：

1. **不放宽 `MarketDataService` 的 strict Historical cursor / coverage fail-closed 合同**；
2. **SuBing current-read 私有编排必须显式识别 Canonical edge，再选择“latest page bootstrap”还是历史 cursor**；
3. **任何 Historical Bar 仍必须受 snapshot cutoff 约束，不得引入未来 Bar / 数据泄漏**；
4. **SuBing research API 失败只能让 SuBing observation unavailable，不能让基础行情 K 线消失**；
5. 不修改 SuBing 公式、Calibration、same-boundary resolver、Lifecycle 机器语义、Alert Rule、Scope 或通知语义。

## 2. 事故现象与证据

2026-08-20 production Web 在 `JM 焦煤 / 15m / 苏冰` 场景出现：

```text
series display identity: contract
frequency: 15m
visible bars: 0 bars
Canonical coverage: 2026-08-18T13:16:00Z → 2026-08-20T07:00:00Z
Market display state: Live
Market phase: 交易中
SuBing: Factor 快照不可用
```

同一页面底部 `MFM_FUTURES_V1_FREQUENCY_UNSUPPORTED` 属于 60m-only 的主力照妖镜 Futures V1 正常能力边界，与本故障无因果关系，不纳入本任务。

当前 production `v1.6.3` 与 develop 的相关 SuBing current-read / Web 展示链在本问题上保持同一基本结构，因此本规格以当前 `develop` 为实现基线。

### 2.1 已确认的代码链

SuBing overlay 会把用户图表 identity 解析成当前主力真实合约：

```text
selectedOverlay = subing
→ resolveEffectiveSeriesIdentity()
→ series_kind = contract
→ contract = selectedDominant.actual_contract
```

API current snapshot：

```text
GET /api/v1/market/research/subing
→ build_subing_read_service(session)
→ SubingReadService.snapshot(request, datetime.now(UTC))
```

Intraday Historical seed 当前进入：

```text
SubingReadService._aligned_intraday_series()
→ _historical_intraday_segment(... cutoff=now)
→ history_page(before=cutoff + 1 microsecond)
→ MarketDataService.query_page()
→ _physical_page_bars()
```

`MarketDataService._physical_page_bars()` 对显式 cursor 保持 strict fail-closed：当 newest candidate partition 的 `coverage_end < request.before` 时返回 `DATASET_OR_PARTITION_MISSING`。

这与 Market Web 正常 current display 的读取方式不同。`MarketReadService._canonical_end()` 明确使用：

```text
history_page(before=None, limit=1)
```

先取得最新 Canonical edge；随后 Live 只从该 seam 之后读取 Redis Overlay。这才符合项目既定的：

```text
Historical Canonical
+
Transient Live Observation
```

分层合同。

### 2.2 Runtime exact error 的实现前 Gate

当前代码数据流已经能确定 cursor 语义冲突，但本次对话未直接读取 production Network 返回体。因此实现任务的第一个测试必须把 production 形态固化成 red reproduction：

```text
Canonical edge < processing now
+ current dominant contract
+ 15m / 5m SuBing intraday snapshot
+ Live state 可用
```

预期在未修复基线上稳定复现：

```text
MarketDataError("DATASET_OR_PARTITION_MISSING")
```

若 red test 得到的不是该错误，必须停止实现并重新执行根因调查，不得在本规格假设上继续叠加修复。

## 3. 权威边界

本修复必须继续服从以下 active canonical：

- `STATUS.md`：当前 release / Runtime / SuBing / Alert 实施状态；
- `AGENTS.md`：唯一开发执行规则与受控外部操作边界；
- `docs/DEVELOPMENT.md`：个人开发和本地验证流程；
- `PROJECT_SOURCE.md`：Data Foundation Frozen、唯一 Historical Gateway、Live Observation 边界；
- `DECISIONS.md`：MarketDataService 唯一查询入口、SuBing / Alert 长期决策；
- `docs/superpowers/specs/2026-08-19-subing-lifecycle-v2-design.md`：SuBing V1 冻结边界与 Lifecycle V2 research-only 语义。

若实现过程中发现本规格与上述 active canonical 冲突，必须 fail-closed，以 active canonical 为准并停止扩大修改范围。

## 4. 冻结边界与禁止范围

以下内容本任务全部禁止修改：

```text
DatasetKey
八表 Market Catalog
Canonical Parquet 语义 / 月分区模型
MarketDataService strict cursor / partition / coverage fail-closed
RQData provider / HistoricalDataManager 写路径
Redis Live 数据模型
Subing Factor 公式
accepted calibration: subing_intraday_v1
Subing Signal 条件
resolve_same_boundary_subing_signals()
5m / 15m 优先与 companion 语义
SuBing Lifecycle V2 状态机 / policy / formula_version
subing_entry_signal_v1 Rule 语义
Alert Scope / Event schema / notification
Execution Review
main / tag / release / Runtime promotion
真实通知 / DB / Canonical 写入
订单路径 / auto_order=false
```

特别禁止通过以下方式“修好页面”：

- 放宽 `MarketDataService._physical_page_bars()` 对显式 cursor 的 strict 检查；
- 捕获任意 `DATASET_OR_PARTITION_MISSING` 后无条件 fallback 到旧数据；
- 直接读取 Parquet 或绕过 `MarketDataService`；
- 把 `MarketReadService.display_snapshot()` 的 post-close 展示语义引入 SuBing Factor / Alert 计算；
- 用 Redis Live 填补正式 Historical 缺口；
- 在 Web 端伪造 Factor、segment start 或 signal；
- 以“先显示”为理由跨主力区段继承 pre-rank1 warm-up。

## 5. 目标行为

### 5.1 正常交易中：Canonical edge 落后 wall clock

给定：

```text
processing_now = T_now
canonical_end = T_canonical
T_canonical < T_now
current dominant contract identity 一致
Live completed bars 可用
```

SuBing intraday current snapshot 必须：

```text
1. Historical bootstrap 从 latest Canonical page 开始
2. Historical 只保留 bar_end <= snapshot cutoff
3. 如 Lifecycle 需要完整 current-rank1 segment prefix，则继续使用 next_before 向前分页
4. 通过现有 MarketReadService.live_snapshot() 合并 canonical seam 之后 completed Live
5. 继续执行原有 Factor / Signal / Lifecycle 逻辑
```

不得因为 `T_now > T_canonical` 本身返回 `DATASET_OR_PARTITION_MISSING`。

### 5.2 历史 cutoff 位于 Canonical 内部

如果调用方给出的 `cutoff < canonical_end`，必须保留现有历史 cursor 语义：

```text
before = cutoff + exclusive epsilon
```

只读取 cutoff 及以前的 Bar，不能先读取最新 Canonical 后把未来数据带入 Factor / Lifecycle。

换言之，本修复只处理“current snapshot cutoff 已到或超过 Canonical edge”的 seam，不把所有查询改成无 cursor latest-page 模式。

### 5.3 真正缺数据时继续 fail-closed

以下情况仍必须显式失败：

- current dominant physical dataset 不存在；
- 目标 segment 所需 Canonical 月分区缺失；
- pagination identity / cursor / ordering 非法；
- current-rank1 segment prefix coverage 不完整；
- contract / dominant / trading-day identity 冲突；
- active canonical 物理不可读。

修复不得把“Canonical edge 正常落后 wall clock”和“Historical 真缺口”混为一类。

## 6. Backend 设计

### 6.1 Canonical edge 先于 Historical seed 决策

Intraday `SubingReadService` 当前已经必须读取 5m / 15m 的 `MarketReadState` 来判断 Live identity 和 availability。实现应调整编排顺序：

```text
for 5m / 15m
    state(identity, now)
    ↓
    state.canonical_end
    ↓
    选择 Historical bootstrap cursor
    ↓
    Historical segment
    ↓
    existing Live merge
```

不新增第二个 Canonical edge resolver，也不直接查询 Catalog。

### 6.2 Historical bootstrap 选择规则

对 intraday private read helper 冻结以下规则：

```text
if canonical_end is not None and cutoff >= canonical_end:
    first_page.before = None
else:
    first_page.before = cutoff + 1 microsecond
```

原因：`MarketDataService` 的显式 cursor 是 exclusive historical cursor；`canonical_end + 1 microsecond` 本身位于 partition coverage 之外，会被 strict contract 正确拒绝。只有 `before=None` 表达“从最新已发布 Canonical edge 开始”。

该规则必须同时覆盖：

1. Lifecycle policy 正常时的 `_historical_intraday_segment()`；
2. Lifecycle policy invalid / disabled 时仍需保留 V1 SuBing 的 intraday fallback read path。

本任务不要求改变 1d SuBing 的读取语义。

5m 与 15m 必须分别使用各自 `MarketReadState.canonical_end` 作决定，不能以一个频率的 edge 代替另一个频率。
如果 `state()` 返回后 Canonical 并发推进，导致 `before=None` 的第一页出现 `bar_end > cutoff`，该页不得直接
裁剪后继续使用；实现必须改用 `before=cutoff + 1 microsecond` 重新执行 strict historical read，以保持
与历史 cutoff 相同的 300-Bar projection 和因果语义。

### 6.3 Null bootstrap cursor 的 pagination 校验

SuBing 私有 `_validate_history_page()` 当前把 `request.before is None` + `has_more_before=True` 判为非法，这与 latest-page bootstrap 不兼容。

修复后第一页允许：

```text
request.before is None
page.has_more_before == True
page.next_before == page.bars[0].bar_end
```

从第二页开始仍必须要求：

```text
request.before is not None
page.next_before == page.bars[0].bar_end
page.next_before < request.before
```

所有其它既有校验继续保留：

- request identity exact match；
- canonical_coverage 与 page bars exact match；
- contract query 不返回 resolved contract segments；
- page size 不超过 limit；
- bar_end 严格递增；
- duplicate page / duplicate bar_end 拒绝；
- `has_more_before=False` 时 `next_before is None`。

### 6.4 Cutoff causality

即使 first page 使用 `before=None`，任何传入 Factor / Lifecycle 的 Historical Bar 仍必须满足：

```text
bar.bar_end <= cutoff
```

这条要求必须在 page bootstrap 与 full-segment assembly 之间保持显式，不能依赖“current API 通常 now 大于 Canonical edge”的偶然事实。

若测试使用一个早于最新 Canonical 的历史 `now`，必须继续证明：

- cutoff 之后 Bar 不进入 projection；
- cutoff 之后 Bar 不参与 lifecycle continuity / pivot / trigger；
- 输出与旧历史 cursor 语义保持一致。

### 6.5 Live merge 保持不变

完成 Historical seed 后继续复用现有：

```text
MarketReadService.state()
MarketReadService.live_snapshot()
_merge_completed_bars()
```

Live 仍只接在 Canonical seam 之后：

```text
canonical bar_end 优先
live 相同 bar_end 不覆盖 canonical
live 只接受 current segment / trading day / completed boundary
```

不得引入新的 live store 读取方式，不得把 post-close display overlay 变成 SuBing Factor 的正式输入。

## 7. Frontend 降级设计

### 7.1 成功路径不变

当 SuBing snapshot 可用时：

```text
visibleBars
= current dominant contract bars
  filtered by snapshot.segment_start_trading_day
```

继续保持 current-rank1 segment-local 展示，不显示 pre-rank1 warm-up。

### 7.2 Error 路径保留基础 K 线

当基础 `useMarketSeries()` 已成功加载、但 SuBing snapshot 请求失败时：

```text
subingError == true
→ visibleBars = bars.value
```

此时只降级 SuBing observation：

```text
Factor / Signal / Lifecycle = unavailable
K 线 / 成交量 / OI = 继续展示当前 effective contract 行情
```

不得再返回 `[]`。

建议将错误提示明确为：

```text
苏冰 Factor 快照不可用；K 线保留当前合约行情
```

避免用户把“Factor unavailable”误解成行情数据也不可用。

### 7.3 Loading 路径保持 segment 安全

`subingLoading == true` 且尚无 snapshot 时，不要求提前展示未过滤的完整 contract history。

原因：在不知道 `segment_start_trading_day` 前直接展示全部 contract bars，可能短暂显示 pre-rank1 数据，与 SuBing segment-local 观察语义冲突。

因此：

- loading 期间可继续保持当前 loading / blank 行为；
- 只有明确 `subingError == true` 后才进入基础 K 线 fallback；
- snapshot 成功后立即恢复 segment-filtered bars。

### 7.4 Error fallback 不授权更早分页

SuBing snapshot error 时 segment start 未知，因此 `canLoadEarlier` 不应因 fallback 自动放宽。

基础 K 线仅保留当前已成功加载页；不得借 error fallback 绕过 SuBing current segment 的“可向前加载”边界。

## 8. API 与合同兼容性

本修复不新增、不删除、不改名任何 `/api/v1/market/research/subing` 字段。

保持：

```text
symbol
product_name
frequency
actual_contract
dominant_mapping_date
segment_start_trading_day
source_mode
live_observation
live_reason
macd_policy_id
signal_macd_policy_id
calibration_state
calibration_id
primary
companion
primary_signal
resolved_signal
lifecycle
```

HTTP 错误合同也不放宽：真正的 `MarketDataError` / `SubingCalibrationError` 仍按现有 API 映射为 409；本任务只是消除一个把正常 Canonical / Live seam 错判成 Historical 缺口的内部调用错误。

## 9. Alert Runtime 影响边界

`AlertRuntime` 的 `subing_entry_signal_v1` 直接复用 `SubingReadService.snapshot()`，因此这不是单纯 Web UI fix。

实现必须证明以下 Alert invariants 不变：

```text
只消费启动后自然 completed 5m / 15m Event
5m 同 15m boundary 的延后规则不变
event Bar / trading_day / primary snapshot identity exact match
resolved_signal 仍由现有 resolver 决定
无 replay / backfill / retry / synthetic补发
Event / notification 语义不变
auto_order=false
```

禁止因为此次 read-seam 修复补评或补发过去未生成的 SuBing Event。

## 10. 测试设计

实现必须遵循 red → green，先固定故障再改生产代码。

### 10.1 Backend red reproduction

新增最小回归；首个 RED 必须通过临时 Catalog / Canonical Parquet 与真实 `MarketDataService` 查询路径触发，
不能由 fake reader 直接抛出预设错误：

```text
contract = current rank1
frequency = 15m（并覆盖 5m）
canonical_end = 07:00Z
processing_now = 13:43Z
state.live_available = true
live contains completed bars after 07:00Z
```

未修复代码必须稳定证明 current SuBing Historical seed 因 explicit `before=now+epsilon` 命中 strict cursor failure。

### 10.2 Latest bootstrap + backward pagination

覆盖：

- first page `before=None` + `has_more_before=True` 合法；
- next page 使用 exact `next_before`；
- 直到 `segment_start_trading_day` 的 prefix 完整；
- duplicate bar / invalid next_before / identity mismatch 继续 fail-closed。

### 10.3 Cutoff / future-leakage regression

构造 `cutoff < latest canonical_end`：

- 仍走 explicit historical cursor；
- cutoff 后 Bar 不进入 Factor；
- cutoff 后 Bar 不进入 Lifecycle；
- output identity 与 cutoff 对齐。

### 10.4 Genuine missing data regression

至少证明：

- physical partition 真缺失仍报错；
- segment prefix gap 仍报错；
- 不允许 fallback 到更旧月或跨频数据。

同时保留一个直接 `MarketDataService` contract test，证明 explicit cursor 超出已发布 coverage 的 strict behavior 未被修改。

### 10.5 V1 / Lifecycle zero-regression

至少运行并覆盖：

```text
SubingReadService focused tests
Subing API tests
SuBing Factor / Signal tests
SuBing Lifecycle tests
Alert Runtime SuBing tests
```

必须确认：

- Factor 数值不变；
- Calibration identity 不变；
- primary / companion / resolved_signal 语义不变；
- Lifecycle current prefix 与 transition 语义不变；
- Alert natural event identity / no-backfill 行为不变。

### 10.6 Web regression

至少覆盖三种状态：

1. snapshot success：继续按 `segment_start_trading_day` 过滤；
2. snapshot loading：不提前暴露 pre-rank1 bars；
3. snapshot error：基础 `bars.value` 仍进入 `KlineChart`，header 不得变成 `0 bars`，同时显示 SuBing unavailable 提示。

优先在现有 Market research / chart e2e seam 增加 route mock，不新增第二套测试框架。

## 11. 允许修改范围

预计实现只需要落在以下现有边界：

```text
services/quant-api/app/market_data/subing_read_service.py
services/quant-api/tests/data_foundation/test_subing_read_service.py
services/quant-api/tests/test_subing_api.py（仅在 API regression 需要时）
services/quant-api/tests/test_alert_runtime*.py（按现有实际文件选择）
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/src/components/market/SubingStatusStrip.vue（若更新降级文案）
apps/quant-web/src/composables/useSubingObservation.ts（仅在现有 seam 无法表达时）
apps/quant-web/tests/* / e2e/market-research.spec.mjs（按现有测试组织选择）
```

实现者可以在上述同一职责内抽取一个 **private helper**，但不得新增公开 service、数据库表、Redis key、API endpoint、research framework 或第二条行情读取链。

## 12. 验收标准

全部满足才允许进入实现 Review：

### Backend

- [ ] red test 在旧逻辑稳定复现 production 形态的 strict cursor failure；
- [ ] `canonical_end < now` 时 SuBing 5m / 15m current snapshot 不再仅因 wall-clock 超过 Canonical edge 失败；
- [ ] Historical seed 从 latest Canonical edge 正确启动，并能按 `next_before` 回溯到 current-rank1 segment start；
- [ ] 所有输入 Factor / Lifecycle 的 Historical Bar 均满足 `bar_end <= cutoff`；
- [ ] 真正 partition / coverage / identity / pagination 异常仍 fail-closed；
- [ ] `MarketDataService` 源码和 strict contract 不因本修复放宽。

### Web

- [ ] SuBing snapshot success 时 segment-local 过滤完全不变；
- [ ] SuBing snapshot error 时基础 K 线继续显示，不再出现“Canonical coverage 有值但 0 bars”；
- [ ] error fallback 不开放未知 segment 的更早加载；
- [ ] Factor / Lifecycle unavailable 状态清晰，不伪造研究结果。

### Zero-regression

- [ ] SuBing V1 Factor / Signal / same-boundary resolver 无公式或 contract 变化；
- [ ] Lifecycle V2 policy / reducer / formula_version 无变化；
- [ ] Alert `subing_entry_signal_v1` 不新增补发、重试、回放或 synthetic 路径；
- [ ] Data Foundation / Catalog / Canonical / Live storage 无变化；
- [ ] `auto_order=false` 不变。

### Engineering

- [ ] 按 `TESTING.md` 跑受影响 backend focused tests；
- [ ] Ruff PASS；
- [ ] Mypy PASS（受影响 source set）；
- [ ] Web unit PASS；
- [ ] Web production build PASS；
- [ ] 相关 Playwright / e2e regression PASS；
- [ ] secret scan / diff check PASS；
- [ ] 独立 Review 对 Lane 3 读 seam 给出 Critical=0 / Important=0 后，才允许集成 `develop`。

## 13. 开发与 Gate

本修复实现属于 Lane 3：不是因为它会执行真实写入，而是因为修改的是 **正式 SuBing Signal / Alert 共用的可信读取口径**。

推荐实现流程：

```text
Sol + 高推理
新独立会话
Plan-only → 人工批准
独立 task branch / worktree from develop
TDD red → green
独立 Review
通过后 task → develop
```

允许在代码 Review 通过后合入 `develop`，但该动作不授权：

```text
main / tag / release
production Runtime promotion / reload
Scope mutation
真实通知 canary / send
DB / Canonical 写入
历史 Event 补发
```

如需部署验证，必须另行取得当次范围明确的 Runtime switch / reload 意图。

## 14. 实现者重点审查项

Review 必须逐项确认：

1. 是否只修 SuBing private current-read seam，而没有放宽 `MarketDataService`；
2. `before=None` 是否只在 `cutoff >= canonical_end` 的 latest-bootstrap 条件下使用；
3. 是否存在任何 cutoff 后 Bar 进入 Factor / Lifecycle 的路径；
4. Null bootstrap cursor 的 pagination validation 是否仍严格；
5. Lifecycle policy invalid 时 V1 fallback 是否同样不受 live seam bug 影响；
6. Web fallback 是否只在 `subingError` 后启用，而非 loading 时提前显示 pre-rank1 history；
7. Alert Runtime 是否保持 event identity、same-boundary、no replay/backfill 语义；
8. 是否错误修改 `STATUS.md`、提前声明 Runtime Ready、策略有效或自然 Canary 完成；
9. 是否误触 main、tag、Runtime、Scope、通知或真实数据写入。

## 15. 最终判定口径

本修复完成最多只能得出：

```text
SuBing current observation 的 Historical / Live seam bug 已按回归测试修复，
Web 在 SuBing snapshot unavailable 时可保留基础行情显示，
且既有 Factor / Signal / Lifecycle / Alert 语义通过零回归验证。
```

不得扩写为：

```text
SuBing 策略有效
自然 Event 已验收
Alert Runtime Ready
可以发布 production
可以 Runtime promotion
```

这些仍分别服从现有 Candidate Validation、Natural Canary、release 与 Runtime Gate。
