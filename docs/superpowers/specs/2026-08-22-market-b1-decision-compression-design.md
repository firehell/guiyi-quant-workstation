# Market B1 Decision Compression Design

日期：2026-08-22

状态：APPROVED_FOR_IMPLEMENTATION

基线：`develop@2d2cbca0b8cf765523bcd260565e94a53afa5238`

## 1. 目标

把 Market Web 从“把很多研究事实同时展示给用户”收敛为一条明确的个人决策漏斗：

```text
首页：从 active 60 中减少搜索空间
→ 详情页：在 5~10 秒内验证是否值得继续等待
→ Alert：正式 Event 出现时打断用户
→ Execution Review：人工决策、真实执行和复盘
```

本设计只重排现有 Web 信息架构，并增加极薄、确定性的前端 view projection；不建立新的机会领域，不新增后端服务、数据库、Runtime consumer 或策略评分系统。

## 2. 当前事实与约束

当前系统已经具备：

- active universe 60 品种；
- Market Radar：actual-dominant Canonical D1 全市场快照；
- Product Research：D1/W1 趋势、20 日位置、量比、OI、ATR 等单品种研究事实；
- Product Workspace：K 线、SuBing、HTDY、主力照妖镜 V2 等现有观察能力；
- Alert：正式 Event 与当前正式信号入口；
- Execution Review：SuBing Event 的人工 Decision / Episode / Execution / Review。

长期边界保持：

- `MarketDataService` 是 Historical 唯一入口；
- Live 仅 observation；
- `auto_order=false`；
- research evidence 不自动排名、winner、promotion；
- 不因 Web 信息架构调整修改策略公式、Alert Rule/Scope 或 Runtime。

## 3. 五问价值 Gate

### 3.1 未来一年是否真实使用

会。首页“先看谁”和详情页“值不值得继续等”属于每天都可能使用的高频动作。

### 3.2 不做是否影响项目价值

会，主要影响：

- 发现机会：当前 Radar 从 60 压缩到最多 10 个 attention，但仍需用户二次组合原因；
- 减少盯盘：当前首页把 summary、scatter、attention、全市场表同时展开；
- 执行一致性：当前详情页正式事件、当前策略观察、研究明细的视觉层级接近；
- 复盘证据：不直接新增证据，但让 Alert / Execution Review 的既有证据链更容易被正确使用。

### 3.3 是否可直接复用现有能力

可以，约 90% 直接复用现有 Radar / Product Research / Alert / Execution Review / Product Workspace。

### 3.4 是否是真实业务复杂度

真实复杂度只有两层：

```text
首页筛选
详情验证
```

统一 Opportunity domain、统一 Candidate adapter、综合 score、跨策略 ranking 都属于当前不需要的提前抽象。

### 3.5 半年后是否容易理解、修改、删除

必须满足：新增逻辑保持在少量前端 pure utility + 展示组件中；删除 B1 不需要改后端、DB、Runtime 或研究协议。

## 4. 方案比较

### 方案 A：首页承担完整判断

首页同时引入周线、小周期、SuBing/N/JDJ/主力照妖镜等状态，直接输出完整机会结论。

问题：首页会逐步变成隐藏的策略编排系统，详情页失去职责，长期维护复杂度高。

### 方案 B1：D1 粗筛 + 详情验证（采用）

首页只用现有 Radar D1 事实做 0~3 个“优先检查”；周线、小周期和当前策略状态全部留在详情页验证。

优点：

- 不改后端；
- 不复制 Product Research；
- 首页职责非常稳定；
- 详情页继续承载研究能力，但默认只展示完成验证所需内容。

### 方案 B2：首页增加周线过滤

比 B1 更少误点，但需要扩全市场 Radar 读取/投影周线。

暂不采用。只有实际使用证明“频繁点入后因周线冲突立即退出”时再评估。

### 方案 C：统一 Opportunity Model

建立统一机会状态、来源 adapter、ranking 和解释层。

当前明确拒绝：没有对应成熟业务和研究 Gate，属于过度设计。

## 5. 产品职责冻结

### 5.1 首页 `/market`

只回答三个问题：

1. 当前有没有正式事项需要处理？
2. 没有正式事项时，哪 0~3 个品种值得先打开检查？
3. 如果用户主动想研究全市场，如何展开原有 Radar 能力？

首页不回答“最终是否应该交易”。

### 5.2 详情页 `/market/chart`

只回答：

```text
这个品种现在值得继续等待吗？
```

默认验证顺序固定为：

```text
1. 现在：是否有正式 Event / Execution Review 状态？
2. 市场背景：周线、日线是否支持？
3. 当前观察：当前 Overlay 的策略/研究状态是什么？
4. 位置 / 参与：20日位置、量比、OI、ATR 是否值得继续观察？
5. 提醒：现有 Rule 是否启用？
6. 更多研究：按需展开详细 Factor / Lifecycle / Alert history / 数据上下文。
```

### 5.3 Alert

仍是唯一“正式 Event 打断”层，不由 B1 创建第二套通知语义。

### 5.4 Execution Review

仍负责人工处理与复盘；B1 只复用现有 event-state 读接口，不修改其业务合同。

## 6. 首页 B1 设计

### 6.1 首屏结构

首屏顺序固定：

```text
需要处理
优先检查
展开全市场研究
```

默认不展开：

- Market Summary；
- Price × OI Scatter；
- 旧“值得关注”；
- 全市场表；
- 板块 Tabs。

这些能力全部保留在同一个 `/market` 页面内的原生 disclosure 中，不新增 `/market/radar` 路由。

### 6.2 优先检查语义

名称固定为“优先检查”，不是：

- 推荐交易；
- 最佳机会；
- 买入/卖出推荐；
- 机会分数。

每个卡片只允许：

- 品种；
- `多头观察 | 空头观察`；
- 2~3 个已有 Radar 原因的中文投影；
- 最多 1 个风险提示；
- `检查详情`。

不展示综合分。

### 6.3 Focus qualification

只消费现有 `MarketRadarItem.reason_codes`，不新增阈值。

多头候选必须：

```text
ema21_up
AND 至少一个：
  price_move_up
  volume_expansion
  oi_increase
```

空头候选必须：

```text
ema21_down
AND 至少一个：
  price_move_down
  volume_expansion
  oi_increase
```

以下不能单独使品种进入 Focus：

```text
near_20d_high
near_20d_low
high_volatility
oi_decrease
```

它们只能作为位置/风险上下文。

### 6.4 Focus ordering

不计算总分。使用透明 tuple ordering：

```text
1. 同向支持原因数量 DESC
2. oi_increase true 优先
3. volume_expansion true 优先
4. 方向性 price_move true 优先
5. turnover DESC；null 视为最低
6. symbol ASC，保证稳定排序
```

最多取前三；不为凑满 3 个降低 qualification。

### 6.5 中文投影

方向：

```text
ema21_up   -> 多头观察
ema21_down -> 空头观察
```

主要原因：

```text
price_move_up    -> 价格上涨
price_move_down  -> 价格下跌
volume_expansion -> 放量
oi_increase      -> 增仓
near_20d_high    -> 接近20日高位
near_20d_low     -> 接近20日低位
```

风险：

```text
oi_decrease     -> 减仓推动
high_volatility -> 高波动
```

若同时存在两个风险，只展示 `减仓推动`；完整原因仍可在全市场研究中查看。

### 6.6 0 个是合法结果

0 个时显示：

```text
当前没有同时满足趋势与参与条件的优先检查品种。
不用主动遍历全市场；等待后续市场变化或正式提醒。
```

### 6.7 freshness

#### `current`

正常生成 Focus。

#### `pending_after_market`

允许生成 Focus，但标题明确：

```text
基于 {data_as_of} 完整日线 · {target_as_of} 盘后更新待完成
```

不得伪装成目标日数据。

#### `degraded`

不生成 Focus Top3。显示：

```text
优先检查暂不可用：Radar 数据不完整。
```

并保留既有 stale / unavailable 警告。

## 7. 详情页 B1 设计

## 7.1 默认验证态

桌面宽屏默认保持 K 线 + 右侧“当前检查栏”。

默认用户不展开任何深度研究，也能完成四步验证：

```text
现在
→ 市场背景
→ 当前观察
→ 位置 / 参与
```

### 7.2 “现在”必须以正式 Event 为准

“现在”不使用 SuBing current snapshot 冒充正式 Event。

数据来源：

- `getProductCurrentAlertEvents(symbol)`；
- 对可进入 Execution Review 的 Event，复用现有 `getEventStates(event_ids)`；
- 不新增后端接口。

状态投影：

```text
无当前 Event -> 当前无正式事件 / 继续观察
pending_decision -> 正式事件待处理 / 记录执行
open -> 已有 OPEN Episode / 查看交易
pending_review -> 待复盘 / 去复盘
done -> 已处理 / 查看记录
```

HTDY 若没有 Execution Review state，仍可显示“今日正式提醒记录”，但不得伪造 Decision / Episode 状态。

### 7.3 市场背景

只使用 `ProductResearchResponse.daily_trend` 与 `weekly_trend`。

固定投影：

```text
up + up       -> 同向偏多
 down + down  -> 同向偏空
neutral + neutral -> 中性
任一 unavailable -> 数据不足
其余组合 -> 未共振
```

UI 显示周线、日线两个方向和一个结论；不生成交易建议。

### 7.4 当前观察

只显示当前 selected Overlay，不同时铺开所有策略。

#### `none`

```text
当前未选择策略观察
```

#### `subing`

显示：

- primary / companion 的方向摘要；
- current `resolved_signal` 或 `primary_signal` 的既有语义；
- lifecycle stage / progress；
- `Research only` 标签只绑定 Lifecycle V2，不覆盖正式 SuBing V1 Signal 语义。

`研究确认` 绝不能显示成正式 Event。

#### `htdy`

显示最新 HTDY observation 与时间，并固定说明：

```text
原始观察可能重绘，仅供人工观察
```

### 7.5 位置 / 参与

默认只显示四项：

```text
20日位置
量比20
OI 1D
ATR 分位
```

不在这里生成“强/弱/最佳”等二次评分。

### 7.6 提醒

复用现有 `ProductAlertRules` 与 Runtime status。

提醒开关只出现一次；“更多研究”内不再复制一份提醒设置。

### 7.7 更多研究

默认折叠，包含现有能力：

- SuBing 详细 Factor / Lifecycle；
- 今日提醒记录；
- Price / Volume / OI 日线归一化观察；
- 数据 / 合约 / Runtime 上下文；
- 历史读取边界。

不删除研究能力，只降低默认视觉权重。

### 7.8 Toolbar

一级保留：

```text
市场
品种
真实主力 / 主连
周期
Overlay
图表设置
全屏
```

`图表设置` 内合并：

- EMA10 / EMA60；
- 指定真实合约。

现有本地偏好语义尽量保持，不做无关 migration。

### 7.9 Identity / Runtime 状态

正常状态压缩为一行：

```text
AG2601 · Live · 交易中 · 数据正常
```

保留：

- 当前真实合约；
- Historical / Live / post_close；
- market phase；
- after-market failure。

原则：正常信息安静，异常信息提高显著度。

## 8. 组件边界

### 8.1 新增 `marketFocus.ts`

纯前端 view projection：qualification、排序、reason/risk 投影。

禁止：

- 网络请求；
- localStorage；
- strategy/candidate import；
- score；
- state machine。

### 8.2 新增 `MarketFocusList.vue`

只负责 Focus 展示，不复制筛选算法。

### 8.3 新增 `productCheck.ts`

只负责详情页 view summary：market background、当前 Event 状态和文本投影。

### 8.4 `ProductResearchSidebar.vue`

重构并改名为 `ProductCheckSidebar.vue`，使文件名与新职责一致。

### 8.5 旧重复组件

如果完成重构后以下组件无引用，应删除：

- `ProductFormalSignalCard.vue`；
- `SubingStatusStrip.vue`。

删除前必须确认其关键 loading/error/unsupported/fail-closed 信息已进入 `ProductCheckSidebar`，不得因为视觉收敛隐藏数据异常。

## 9. 数据流

### 首页

```text
GET /market/research/radar
→ MarketRadarResponse
→ selectMarketFocus(items)
→ MarketFocusList

同一 radar payload
→ 默认折叠的 Summary / Scatter / Attention / DetailTable
```

### 详情

```text
MarketData / WebSocket -> KlineChart
ProductResearch -> 市场背景 + 位置/参与 + 更多研究
SubingReadService API -> 当前观察 + 深度 SuBing
HTDY local derived markers -> 当前观察
Alert API -> 正式 Event + 提醒 + 今日记录
Execution Review event-states -> Event action/state
```

任何一条研究/Alert 辅助链失败都不得清空已经成功读取的 K 线。

## 10. Error / unavailable 设计

### 首页

- Radar fetch 初始失败：保持现有 unavailable；
- manual refresh 失败：保持上一成功快照；
- `degraded`：Focus fail-closed；
- `pending_after_market`：保留上一完整快照并明确时点。

### 详情

- Product Research unavailable：市场背景和位置显示不可用，K 线保持；
- SuBing unavailable：当前观察显示不可用，K 线保持；
- Alert unavailable：正式 Event / 提醒区域显示不可用，不推导“无事件”；
- event-state unavailable：仍显示 Event fact，但不伪造处理状态；
- HTDY observation absent：显示暂无当前观察，不推导方向。

## 11. Responsive

### `>= 1200px`

K 线 + 检查栏并排，检查栏默认可见。

### `980~1199px`

保持单列 K 线，复用现有 Drawer 机制；Toolbar 入口文案从“研究”调整为“检查”。

### `< 980px`

不得出现横向溢出。可继续复用现有窄屏行为，但检查信息必须仍可访问且顺序不变。

验收重点仍是仓库既有桌面视口：

```text
1440 × 900
1280 × 720
1024 × 768
```

## 12. 非目标

本任务明确不做：

- 后端 Radar 新字段；
- 全市场 W1 扫描；
- OpportunityService / OpportunityModel；
- score / probability / winner / best symbol；
- SuBing/N/JDJ/MFM 统一 adapter；
- 新 Market route；
- 新 DB / migration；
- Alert Rule/Scope/notification 修改；
- Runtime switch；
- Canonical / Redis 写入；
- 自动交易。

## 13. 测试策略

### Unit

新增：

- `marketFocus.test.ts`：qualification、ordering、risk、0~3、stable tie；
- `productCheck.test.ts`：周/日背景、Event state、unavailable 投影。

### Browser E2E

修改现有：

- `market-radar.spec.mjs`：首页 Focus / disclosure / freshness；
- `market-research.spec.mjs`：正式事项顺序、详情验证态、研究展开态、SuBing/HTDY 分层、响应式。

### Full Web

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
pnpm --dir apps/quant-web build
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

## 14. 完成定义

### 首页

- 首屏默认只显示“需要处理 → 优先检查 → 展开全市场研究”；
- Focus 为 0~3；
- degraded 不输出 Top3；
- pending 明确旧完整快照时点；
- 原全市场能力可展开访问；
- 无综合分、推荐交易、最佳机会文案。

### 详情

默认不展开深度研究时，用户可以直接回答：

1. 现在有没有正式事项？
2. 周线/日线是否支持？
3. 当前 Overlay 在什么状态？
4. 量价位置是否值得继续观察？

正式 Event、当前策略观察、research-only Lifecycle 必须视觉和文案分层。

### 边界

- 后端、DB、MarketDataService、Alert、Runtime、策略公式零语义变化；
- `auto_order=false` 不变。
