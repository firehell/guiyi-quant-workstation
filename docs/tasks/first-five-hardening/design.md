# 全局 Review 前五项：数据可信与运行可见性设计

日期：2026-09-17。状态：隔离工作树实施中；本文件不授予生产写入、发布或 Runtime 切换权限。

## 1. 结论与设计基线

建议在现有模块化单体内完成四个可独立验收的改动批次：统一读取完整性校验；修复来源校验与交易日请求；统一换月统计输入；补齐逐品种运行覆盖。先保证输入可信，再让指标与健康页面准确表达这些事实。不增加服务、数据库表、消息队列、第二套缺口台账或自动补数机制。

本轮独立工作树为 `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/first-five-design`，分支 `codex/first-five-design`，起点为 `develop@78515dff718a787f8e11693545114f83682f32ce`。主工作树已有未跟踪文档与 outputs，均保留。五项代码、测试与对应合同已在此工作树实施，仍需独立复审及最终验收；本文保留原设计论证，不构成生产发布或数据操作授权。

原 Review 的基线为 `91e9b911`；本方案重新检查了最新代码。最新基线新增了 D1 来源价格不可用事实与 Newow 断段处理，不能按旧代码设计：

- `PriceUnavailableFact` 与正常 Bar 分离；普通历史消费者保持 fail-closed，只有明确的 Newow D1 quality-aware 入口可以展示断段。
- `NO_TRADE` 与 `PRICE_UNAVAILABLE` 不合并；端点存在、价格可用于计算、数据达到目标日期是不同判断。
- Newow 当前 develop 候选已开放 W1/D1，60m 和完整 explanation 仍受 capability Gate 约束。本方案不扩大其发布面。
- `STATUS.md` 的部署记录不等于本轮 Runtime 实测。本轮不对生产数据受影响范围作已确认声明。

| 原排序 | 问题 | 本方案解决的结果 |
| --- | --- | --- |
| 1 | 普通 MDS 查询和分页不能证明同日分钟完整性 | 在统一入口拒绝缺少应有端点的成功结果 |
| 2 | 来源合约身份丢失、同时间记录可能被静默覆盖 | 错合约和重复响应在合并及发布前失败，授权 refresh 仍可正常更正 |
| 3 | 全局 Live/Alert 健康掩盖个别品种停滞 | 展示实际 Scope 中每个品种、规则和周期的到期完成情况 |
| 4 | 首页与通用研究指标跨主力合约计算 | 目标日主力的同一物理合约历史提供统计输入，显式披露口径 |
| 5 | 分钟补数用时间戳自然日代替交易日请求 | 请求从权威交易日生成，正确覆盖跨午夜、周末和长假夜盘 |

## 2. 全项目取舍

| 路线 | 优点 | 代价与结论 |
| --- | --- | --- |
| 各页面、各策略分别补判断 | 单个页面改动小 | 会继续分叉，补数和 Runtime 仍可能漏检，不采用 |
| **共享入口补强，消费者只处理明确状态** | 复用现有 Calendar、Session、Catalog 和 MDS，能按批次测试 | 会暴露过去被掩盖的数据不足，推荐 |
| 新建统一治理平台、历史健康台账和修复调度 | 能提供更多长期治理功能 | 超过个人工作站当前收益，维护面过大，不采用 |

保持唯一历史链 `RQData → staging/validation → Canonical + Catalog/MainContractMap → MDS`。Live observation 仍独立。MDS 不导入 HistoricalDataManager，不调用 provider，不在读取失败时修复数据。

共享能力复用 `DatabaseCoverageSource.expected_bar_end_pairs_for_trading_days`、`SessionWindowBatch`、合约 lifecycle 和 MainContractMap。新增代码只组织这些事实，不另写交易日或分钟边界算法。已有 Alert/replay 更严格的校验继续有效，不因普通入口补强而降级。

本方案的接口名、错误码和版本名均为拟议设计；实施时按既有类型收敛命名。金融数值沿用 Decimal。除第 4 项明确提出的通用统计输入口径外，不改变策略公式、Marker、ReferenceTrade、Event、成交或收益语义。

领域合同的对应落点如下；本轮不提前修改 accepted canonical：

| 设计 | 实施时对应合同 |
| --- | --- |
| MDS 完整性、分页、质量边界 | `openspec/specs/market-series-query/spec.md` |
| 来源校验、交易日请求与发布 | `openspec/specs/historical-data-maintenance/spec.md`、`openspec/specs/canonical-market-storage/spec.md`、`docs/DATA_CENTER.md` |
| 逐项健康、Scope、heartbeat | `openspec/specs/subing-ths-alert/spec.md`、`docs/DATA_CENTER.md` |
| 同合约统计与 projection | `openspec/specs/market-home-overview/spec.md`、`docs/ARCHITECTURE.md` |

## 3. 第 1 项：MDS 对承诺返回的窗口证明完整性

### 3.1 当前证据

`market_data_service.py::_actual_dominant` 最终按 trading_day 集合判断覆盖，不能发现一天内缺分钟。`query_page` 的分区/日边界检查同样不能代替端点检查。本轮最小复现：权威 Session 为 09:00–09:05，文件只有 09:01、09:05 两根，普通区间查询与分页均成功返回两根。

仓库已有 `expected_contract_replay_endpoints` 和 `validate_contract_replay_coverage`；应抽出/复用底层端点比较能力，而不是让所有普通读取伪装成 Alert replay 请求。

### 3.2 端点身份与判定

内部统一使用有序端点 `(physical_contract, bar_end_utc, trading_day)`。先验证顺序、唯一性与身份，再比较 expected/actual。不能先转成 set 或 dict 后丢掉重复证据。

区间查询保留 `(start, end]` 合同：

1. 通过 Catalog Calendar/Session/lifecycle 解析请求涉及的交易日及应有端点。
2. actual_dominant 按对应交易日的权威 rank1 区间确定物理 owner；物理查询只按指定合约 lifecycle。
3. 按请求边界裁剪 expected，而不是按实际第一根/最后一根缩窗。
4. 读取精确 active URI 后验证 hash、质量、身份和端点有序相等；缺、重复、意外端点分别失败。
5. 非交易窗口没有 expected 时，保持已有空窗语义；不得把休市当缺数，也不得把本应有 Bar 的空返回当正常空窗。

建议底层比较器仅接受 `expected_endpoints`、`actual_endpoints` 和有限错误上下文，输出成功或既有 `MarketDataError` 的分类原因。默认不对外暴露全量缺口清单；给出请求范围、expected/actual 数量及有限缺口样本，不泄漏内部 URI 或 SQL。

### 3.3 分页必须有自己的边界合同

分页不能用“请求 N 根，至少读到 N 根”证明连续，也不能因此扫描整个合约历史。

- 保持 `before` 排他与 `query_page_inclusive` 包含边界两种现有行为，不能相互替代。
- 在现有 history floor、生命周期、分区规划和查询上界内，从权威 expected 取最多 `limit + 1` 个应有端点作为当前页及 sentinel；读取必须覆盖这些端点，而不是从已读到的 Bar 反推应有范围。
- 一个应有端点所在分区缺失，不能跳过该分区再向更早日期凑足 N 根。游标附近缺一根必须失败。
- 首次 latest 页的上界依赖 Catalog 已承诺的历史范围；它证明该历史切片完整，不隐含“已经更新到现在”。Catalog/数据尚未承诺的新日期由显式 as-of 查询、维护审计及 freshness 状态判断。
- 显式 `before` 仍执行现有上界覆盖检查，尤其物理分页当前在 coverage_end 不足时会失败，不能顺手改成向历史回退。响应保留实际截止信息；业务要求固定日期时，先解析该日期的权威完成端点，再使用精确包含/排他边界，不能传任意墙钟时间后放松 coverage。
- `has_more=false` 只能在到达权威允许的历史下界时成立；遇到缺失元数据/分区或扫描预算耗尽，返回明确不足/失败，不能伪装为历史结束。
- 跨页连接用 expected sentinel 校验；分页拼接与相同边界的区间查询结果必须一致。

### 3.4 期货和新 D1 合同

- 跨午夜与周末靠交易日解析；午休不是连续分钟缺口；短尾 60m Bar 使用现有 Session 聚合边界。
- W1 只期待完整交易周最终交易日的周端点；节假日缩短周和周中换主力复用现有 weekly owner 规则，不能按每个交易日期待一根周线。
- 合约上市/到期边界来自 lifecycle；不把上市前或到期后视为缺数。
- `PRICE_UNAVAILABLE` 不因“端点齐全”变为正常 Bar。普通 reader 保留现有质量失败边界；Newow D1 专用 reader 继续验证正常 Bar 与质量事实的互斥并集完整性，再作断段。
- `NO_TRADE` 可以满足来源端点存在性，但不自动满足价格指标输入要求。

### 3.5 性能与一致性

每次请求按合约/月份批量加载 Calendar、Session、Map 和 active partition，复用现有 weekly batching。expected 只生成请求/分页所需窗口，不枚举多年全部分钟。请求内缓存可用，跨请求缓存必须绑定元数据身份，不能永久缓存日历。

同一次读取冻结所用分区引用与映射结果；公共只读 API 沿用既有只读事务。维护发布中的 strict-read 仍在原 Catalog 事务执行，不能强行开启另一个只读事务导致看不到尚未提交的数据。

重点文件：`app/market_data/market_data_service.py`、`coverage_source.py`、`session_clock.py`；只有端点比较确需独立职责时新增同目录小型 `series_coverage.py`，不做大规模 MDS 拆分。

验收：上述 5 根只存 2 根的复现必须失败；完整 5 根成功；缺首页尾端、游标邻接端、跨月整分区都失败；分页拼接保持一致；D1 quality-aware 及 Alert/replay 原有测试继续通过。

## 4. 第 2 项：来源身份、重复记录和发布前验证

### 4.1 当前证据与实际边界

`rqdata_adapter.py::_minute_bars` 将来源行转换为 CanonicalBar 时未先绑定原始 `order_book_id`；`_exchange_daily_rows` 以请求合约归档行，不能用请求参数代替响应身份验证。`historical_data_manager.py::_merged_fetched_bars` 用字典覆盖同端点值，冲突记录会丢失。

已有 Live recovery 行规范化包含严格合约身份检查，应复用相同的原始字段校验规则；本问题不表示 Live recovery 所有入口都缺少校验。

### 4.2 推荐处理顺序

```text
原始响应及既有来源证据
→ 规范化 index/列结构
→ 必填身份、字段类型与时间校验
→ 同响应重复/冲突检查
→ 交易日与 Session 归属校验
→ 按精确 expected 选择目标行
→ Bar / PriceUnavailableFact 分类
→ 批次绑定及全部待发布目标校验
→ 既有 Canonical 原子发布与 Catalog strict-read
```

- 每行必须有可验证的物理 `order_book_id`，精确等于本次请求合约；禁止用请求合约填补缺失响应身份。MultiIndex 经规范化后仍必须保留该字段。
- 分钟时间戳按现有 Shanghai→UTC 规则转换；响应 `trading_date` 必须与 Catalog Session 归属一致。字段缺失、无法唯一归属、合约或日期不一致均失败。
- 日/周源行按其 API 合同验证日期与合约；日线与周线共享同一捕获行不算单响应重复，不改变现有 W1 来源算法。
- 同一响应内同一合约与端点出现两行，**即使数值相同也拒绝**，分类为重复或冲突；避免引入“哪个版本正确”的隐式优先级。同一请求的重跑幂等与单响应重复是两件事。
- 允许 provider 返回请求交易日的完整行集；先校验整个响应的身份、重复和归属，再筛选精确缺口。合法超集不等于允许接收其他合约、其他请求日期或 Session 外的行。
- `BarBatch` 增加可比对的请求身份（DatasetKey 与 expected 端点摘要），manager 不仅检查批次数量，还检查逐批绑定；乱序/错批不得由 `zip` 静默接收。
- manager 合并入口再检查标准化 Bar/质量事实的唯一性，覆盖内部 fake/provider 和未来 adapter，不能只依赖某个 RQData 客户端。

### 4.3 refresh、更正与质量事实

允许已批准 refresh 范围内的新来源值替换旧 Canonical 值；不能把“新旧版本值不同”一概归为同响应冲突。授权集合以当前 `_Target.missing` 等明确 planned fetch/refresh endpoints 为准，不由是否已存在记录推断权限。

合并前区分已有事实、此次唯一来源事实、精确允许替换范围。范围外替换失败；普通补缺不覆盖已有端点。正常 Bar 与 `PriceUnavailableFact` 同端点同时存在失败；质量状态转换沿用已批准的 D1 来源证据与发布合同，必须更新关联证据，不能仅删除质量记录来通过校验。

沿用当前 apply 在发布前预验证全部 fetched targets 的顺序，尽量在第一次 Canonical 写入前发现来源错误。后续磁盘/数据库失败仍遵守既有单分区原子发布与批次部分完成记录；不承诺跨所有分区事务，不自动回滚已提交分区。

来源证据只写既有 capture/审计位置，保留安全错误类型、请求身份与记录摘要，不新建平行 report 体系，不把原始响应或凭据输出到终端。出现错误停止受影响批次；不得追加真实请求“再试试看”。

重点文件：`app/market_data/rqdata_adapter.py`、`historical_data_manager.py`，以及现有 source capture 测试。

验收：错合约、缺身份、相同重复、不同值重复、Bar/质量事实重叠、返回错批均在发布前失败；合法完整日超集可提取缺口；明确 refresh 可更正；重复执行同一已完成计划不形成新写入；后半批错误不能让前半批先发布。

## 5. 第 3 项：逐品种 Live/Alert 覆盖健康

### 5.1 目标与当前证据

Live heartbeat 当前使用全局最近 Bar 和 phase counts；Alert `_record_rule_result` 以 rule 为汇总键，成功品种会覆盖其他品种的问题。因此进程活着、存在一根新 Bar 或一个成功评估，不证明 Scope 中全部项目持续完成。

目标是让 owner 在一个页面看到“哪些品种/周期该完成但没完成、卡在数据还是评估”；不引入自动重试、重放、通知队列或新告警发送。

### 5.2 数据结构与存储选择

分开表达三层：`process_alive`、`transport_available`、`business_coverage`。现有 `available` 的兼容含义不因一个品种滞后就直接变为整个行情源不可用。

每个覆盖项记录：

```text
key: product + physical_contract + trading_day + frequency [+ rule_code]
identity: runtime_commit/root + writer_epoch + scope_digest + rule/formula identity
progress: last_completed_bar_end / last_evaluated_bar_end
          first_unresolved_bar_end / last_success_at / error_code
health: expected_bar_end + state + observed_at
```

不能只增加 per-product 最大时间戳：先漏一根、后来收到更晚一根，同样不证明中间完整。Live 进度来自成功接受的 completed observation，并检测当前 Session 内首次未解决端点；Alert 进度来自实际评价完成及 evaluator 的有效覆盖结果，而不是收到消息或创建了 Event。

推荐复用两个已有 TTL heartbeat 的发布节奏，在 `live:heartbeat`、`alert:heartbeat` 中各新增一个带 `coverage_schema_version=1` 的有界 coverage 区块。**不改 `alert:runtime-status` schema 6 的通知故障/acknowledgment 持久状态**，避免这次健康改造侵入通知并发合同。实施时同步放宽/升级 heartbeat 的严格 reader；不留第二个正式 writer。

coverage 只保存当前运行 Scope 的当前交易日进度及上一未完成日的有限摘要；项目数上限来自 operational 集合 × enabled Rule 的实际支持周期。不得遍历所有历史 Event，也不按每个端点保存无限日志。若多个历史日持续失败，有限摘要保留最早未解决日和受影响日数，不因仅保留一条摘要就声称其他日已恢复。旧版本 heartbeat 没有 coverage 时显示 `UNVERIFIED`，不能从全局绿灯推算逐品种健康。

进程重启生成新 writer_epoch；同 commit 也不得沿用旧进程的成功印象。能从现有已验证 Live window 和 evaluator 状态重建的进度才恢复，其余显示 `UNVERIFIED`，不靠发送历史 Event 来建立健康。

### 5.3 到期规则

Live 范围只取 `operational_products.txt`，Alert 范围取 enabled Rule ∩ 已批准 Scope ∩ operational。不能把未启用周期或 research-only 品种计为失败。

| 场景 | 预期行为 |
| --- | --- |
| 日盘/夜盘尚未产生第一根 completed Bar | `NOT_DUE`，不按开盘瞬间要求 Bar |
| completed 1m 到期 | 复用现有 2 秒 finalization 与 5 分钟 Live freshness 预算，逐品种判断 |
| 分钟级 Alert 的聚合端点到期 | 依该规则实际周期和 Session 尾段产生 expected；输入到齐后建议给 60 秒评估预算 |
| Alert 没有产生信号 | 正常完成评价仍计为成功，不能以 Event 数判断健康 |
| DUPLICATE/STALE 提示 | 只有同一身份已存在有效成功进度才保持完成，不能把跳过当新成功 |
| 午休、夜盘结束、无夜盘品种、节假日 | 不生成休市端点；已有未解决端点不能被 phase=closed 清除 |
| 换主力、Scope 或 Rule 版本变化 | 按新身份重新建立预期；保留上一身份未完成摘要，不能串用旧水位 |
| D1/W1 尚未 Canonical 发布 | `WAITING_CANONICAL`；关联现有盘后计划/运行状态，不在 15:00 后一分钟误报 evaluator 卡死 |
| D1/W1 Canonical 已验证可用 | 评价截止绑定真实 Canonical 更新事件/结果身份；若预定盘后任务 missed/stuck，沿用该任务故障，不能永久等待 |

60 秒是本提案的 Alert 完成预算，需在隔离 60 品种负载验证后纳入明确版本化配置；不能由运行时自动放宽。60m/15m 等按实际 completed 聚合端点计时，不以每分钟要求一次长周期评价。W1 只在该完整交易周到期。

延迟分两层：数据尚未到齐报告 `DATA_LAGGING`，数据已经齐但未完成评价报告 `EVALUATION_LAGGING`；未知 Session/Map/身份报告 `UNVERIFIED` 或现有完整性错误，不按休市掩盖。休市不继续机械累加应有 Bar，上一 Session 的实际漏项仍保留。已收到全部应有端点的品种不会因为休市超过五分钟而变为滞后；以到期端点及其接收证据比较，不能机械复用 `now - last_bar_end`。

### 5.4 组合、展示与兼容

`runtime_health.py` 批量读取两份 heartbeat 与现有 Calendar/Scope 信息，计算期望数量、完成数量、问题清单和最早未完成端点。coverage 是健康投影，不成为行情缺口权威；详情诊断仍走 MDS/既有 Live read，健康读取不调用 evaluator。

整体业务状态：全部到期项完成才是 healthy；部分到期项滞后为 degraded；身份/覆盖证据缺失为 unverified。无到期项显示 not_due；独立的进程或 transport 故障继续优先展示。健康故障不能自动发通知。

Market 首页与详情消费必须同步区分 transport 和 item coverage：A 品种滞后只使 A 的 Live 展示降级，其余 59 个正常品种仍可用。不能简单把新聚合 degraded 写成旧全局 `available=false`，否则健康修复反而熄灭全部报价。Historical 报价与 Live 降级分别披露。

重点文件：`app/market_data/live_market.py`、`app/alerts/runtime.py`、`app/alerts/composition.py`、`app/services/runtime_health.py`、`app/schemas/runtime.py`、`app/market_data/market_read_service.py`、`app/market_data/market_home_live.py`、`app/api/market_live.py`；前端 `runtimeHealthTypes.ts`、`runtimePresentation.ts`、首页 Live 类型/展示及健康详情。回归 recovery/promotion readiness 等 heartbeat 消费者。

验收：60 个品种中一个停止推进，其余持续更新，整体必须 degraded 并精确指出该品种；某规则一个周期卡住不能被另一个成功覆盖；首个缺口不会被更晚端点抹掉；无信号仍 healthy；午休/无夜盘不误报；缺输入与未评价区分；重启、旧 heartbeat 和 Scope 改变不假绿；通知 Event/transport/ack 状态完全保持原有行为。

## 6. 第 4 项：换月统计采用目标日同一物理合约

### 6.1 当前证据

首页从 actual_dominant 拉取 D1/W1 后，将 Bar 数组送入通用 `research_metrics.py`，丢失 segment 边界；`market_research_service.py` 也存在同类路径。两份不同合约的价格、成交量、持仓量不能因为在主连相邻就直接相减或进入滚动窗口。

例如旧主力持仓 100 万、新主力 60 万，不足以得出“市场减仓 40 万”；合约价差也不应进入 ATR 充当真实单合约振幅。本项仅修正首页/通用研究统计，Newow owner 分段、公式和 ReferenceTrade 使用其既有独立合同。

### 6.2 三种输入方案

| 方案 | 后果 | 选择 |
| --- | --- | --- |
| 只截取当前主力 segment | 安全且简单，但每次换月大量指标重新 warm-up，W1 尤其难以可用 | 可用于明确 segment 产品，不作为首页默认 |
| **目标日主力合约的物理历史，含成为主力前的 warm-up** | 同合约可比，复用已有物理行情；历史不足时明确缺数据 | 推荐 |
| 复权/拼接连续序列 | 价格需额外复权规则，持仓量仍不能靠价差调整获得可比性 | 本轮不引入 |

### 6.3 固定计算合同

1. 首页沿用统一完成交易日 T，以 `dominant_segment_for_day(T)` 确定唯一物理合约 C。历史 as-of 请求不能用数据库“最新主力”替代 T 的主力。
2. D1、W1 通用统计都读取 C 的物理历史，严格限制到 T 的完成边界；不让日线和周线各自选不同 owner。
3. 使用 MDS physical 查询取得最多现有 300 根 D1、80 根 W1 的有界输入；成为主力前的同合约历史可用于 warm-up。周线必须在 T 前完整结束。
4. 使用显式截止的分页/区间入口。现有 `contract_daily_bars_as_of` 的“先读 latest 再拒绝未来”路径不能直接承担任意历史 T，需要改为真正有界的物理读取。
5. 昨日/前期比较要求权威相邻交易端点，不能用“最近两根现有行”掩盖缺一天。ATR、均线等继续用原通用 kernel，其输入准备与 seed/warm-up 规则在新 metric policy 中固定。
6. 缺物理历史时，相关指标为 null，原因如 `PHYSICAL_HISTORY_INSUFFICIENT`/`WARMUP_INSUFFICIENT`；不下载、不借旧主力、不自动缩短指标周期。
7. 正常 `NO_TRADE` 行保留来源事实，但价格无效的端点中断通用价格指标有效窗口；不能删除该天后压缩时间序列或把零价格送入 ATR。该输入策略属于本项需要确认的统计语义。
8. `PRICE_UNAVAILABLE` 和其他完整性异常继续通过 MDS 的质量边界失败，不为了统计可用放松普通 reader。合法历史长度不足与数据完整性损坏必须分开，后者不能被宽泛 catch 转为普通 null。

本项保留通用 kernel 的当前参数：趋势 EMA21 使用 `sma_window`；ATR14 使用 `wilder_sma_seed`。现有 ATR 分位计算最多取前 252 个有效 ATR、最少 20 个即可输出，本轮不顺手改成另一套阈值，但响应必须披露实际基准样本数，不能把不足 252 个样本宣称为完整 252 日统计。遇到无效价格，重新建立当前连续有效窗口后仍按这些原参数判断 ready。

首页 participant 与涨/跌/平/不可计算计数仍遵守既有守恒关系：有目标日 D1 的品种不会因某个指标不足就消失，null 不计为平盘；没有目标日有效事实的品种按既有 unavailable/stale 边界处理。周线物理数据完全未建设可显式 unavailable，已声明覆盖却损坏/缺片仍为完整性错误。

明确请求 physical 的研究页面保持指定合约；明确请求 continuous 的既有研究页面仍保留其合成序列身份，不把它标成物理统计。对 actual_dominant 展示，图表可以继续表示主力序列，但旁边统计必须标明“截至 T 的主力 C，同合约历史口径”，避免读者误以为指标来自可见的跨合约图表。

### 6.4 指标身份与派生缓存

统计响应增加 `metric_policy_version=physical_owner_v1`、`metric_contract`、`as_of_trading_day`、输入开始/截止、有效样本数量和 unavailable reason。这些不是可执行策略或收益版本。

`MarketHomeProjectionEnvelope` 当前 schema 2，拟升级为 schema 3，并将 metric policy 与物理输入身份纳入 projection/cache 验证。前端显式 parser、view model、快照缓存必须一起升级；旧统计投影不得在新代码下命中为有效结果。新 reader 对旧投影按不兼容处理，复用既有只读 fallback/显式不可用合同，GET 不删除或重建生产文件。

物理输入身份来自批量查询的 owner 和 Catalog 分区版本/引用，不在 projection 命中路径重读所有 Parquet 计算 hash。保留每个品种至多一次 D1、一次 W1 的有界 Bar 查询，以及批量主力上下文读取，避免同合约方案变成逐指标重复 I/O。若验证身份无法在该预算内完成，应在实现 Review 中调整现有投影身份设计，不增加第二个行情缓存。

这与当前 overview canonical 明写的“两次 actual_dominant 查询”和 schema 2 有明确冲突，属于本方案主动提出的输入合同变化，需要在实施 C 时同步修改上述对应条款。MDS 的 actual_dominant/W1 owner 规则本身不变；指标读取 physical 合约的周历史不能冒充 actual_dominant 的周 owner 序列。

投影失效和刷新继续属于现有维护/盘后流程；本设计不启用 projection 开关。新旧指标切换须同步更新相关 canonical 与 `docs/ARCHITECTURE.md` 的 active 描述，版本变更不触及 Newow formula/reference model。

重点文件：`app/market_data/market_home_overview.py`、`market_research_service.py`、`research_metrics.py`、`market_home_projection.py`、相关 typed schema；前端 `marketHomeTypes.ts`、`marketHomeViewModel.ts`、`marketHomePresentation.ts` 和快照缓存。

验收：制造巨大跨合约价差/OI 差，统计仅使用 C 的前后值，不出现拼接跳变；T 之后发生换月时历史 T 结果不变；同合约历史足够时换月首日仍可计算；不足则显式 unavailable；旧投影不能命中；Newow 既有金样与参考交易完全不变。

## 7. 第 5 项：补数请求携带权威交易日

### 7.1 当前证据

`BarFetchRequest` 当前只带 DatasetKey 和 expected 时间戳；`_minute_bars` 使用这些 UTC 时间戳的 `.date()` 生成 provider 请求日期。分钟所属交易日因此在请求边界丢失，夜盘单点补缺尤其容易请求错日。

RQData 官方 `get_price` 文档区分分钟时间戳与 `trading_date`，示例以 2022-05-12 为起始交易日返回 2022-05-11 夜盘记录。因此不能用 UTC 日期或 Shanghai 自然日替代交易日。[官方接口说明与示例](https://www.ricequant.com/doc/rqdata/python/generic-api)

### 7.2 推荐接口与请求构造

将请求内部端点改为不可变的 `expected_pairs: tuple[(bar_end_utc, trading_day), ...]`。旧 `.expected` 可作为只读派生属性服务现有调用，但不能保留两个可独立修改的事实字段。manager 从第 1 项同一 Calendar/Session authority 解析精确计划端点；如果没有唯一交易日，在 provider 调用前失败。

```text
计划明确缺口 endpoints
→ 与权威 (bar_end, trading_day) 一一匹配
→ 校验仍等于批准的目标集合
→ 按物理合约、连续交易日范围分包
→ provider(start_date=min(trading_day), end_date=max(trading_day))
→ 验证 response.trading_date + Session + contract
→ 仅选择本包 expected endpoints
```

交易日映射及请求边界参与计划/请求摘要与 apply preflight。旧 sealed plan 没有该身份时重新生成 dry-run，不能执行时静默补齐解释；Calendar、Map 或 Session 在 plan 后改变时沿用计划失效机制。

同一合约跨交易日请求采用有界分包；非连续目标交易日优先拆包避免扩大返回量。即使只补一分钟，provider 可能返回一个完整交易日，因此 dry-run 同时说明“目标端点数”和“预计请求交易日/响应规模”，不能按一分钟估算实际配额。预算不足直接停止，不自动追加下载。

### 7.3 必须通过的边界

- 普通前一晚 21:01 与次日 00:01：都按 Catalog 所属交易日请求。
- 周五夜盘属于下一个权威交易日时，按该交易日请求；不写“自然日 + 1”规则。
- 长假前后的 night session 是否存在完全服从 Calendar/Session，不擅自生成节前夜盘。
- 仅夜盘有缺口、日盘已有完整数据时，不能让 min/max 时间戳日期误导请求范围。
- 跨月夜盘：Canonical 的分区身份与 provider 请求交易日都遵守既有定义，不能按时间戳自然月份另选分区。
- 无夜盘品种、Session 元数据缺失、同端点匹配多个交易日，分别按权威规则处理或失败。

重点文件：`app/market_data/historical_data_manager.py::BarFetchRequest`、请求创建/preflight、`rqdata_adapter.py::_minute_bars`；第 2 项同步验证返回的 `trading_date`。不修改已正确使用 request.trading_day 的 Live recovery 请求行为。

验收使用 fake provider 捕获真实调用参数，断言夜盘单点请求的 start/end 是权威交易日；返回另一交易日或错误合约必须失败；缺映射时 provider 调用次数为零；返回完整日的合法超集能精确提取缺口。本轮不需要真实 RQData 下载来证明参数修复。

## 8. 实施批次与依赖

以下是设计完成后的建议实施划分，均尚未开始。每批包含定向回归、按风险独立 Review、必要 canonical 修改与一个可审查提交；不要求额外复制四份 Spec/Plan。

| 批次 | 内容与输入输出 | 完成标准 |
| --- | --- | --- |
| A | 第 1 项：复用端点 authority，补 MDS 区间/分页完整性；输出共享端点比较及明确错误 | 读入口不再把缺口当成功，分页/周线/quality-aware 边界不退化 |
| B | 第 2 + 5 项：请求保留交易日，响应先验证身份/重复，再合并；使用 A 的相同端点事实 | fake provider 参数正确，异常在发布前失败，合法 refresh 和 D1 质量转换保持 |
| C | 第 4 项：以 A 的可信物理输入重建首页/通用统计，升级响应及投影身份 | 换月统计可解释，历史 as-of 稳定，新旧缓存隔离 |
| D | 第 3 项：基于共享 Session 到期规则，增加有界覆盖状态并更新消费者 | 单项故障不假绿、不拖黑全部产品，不改变 Event/通知行为 |

优先 A→B，尽快同时守住读与写；随后 C、D 可分别验收。D 无需依赖 C 的统计口径；若当前 owner 最关心运行漏品种，可在 A/B 之后先交付 D。避免一次把全部改动合成不可定位的大版本。

不包含原 Review 后续项：完整撮合/费用模型、OOS/Walk-forward、通知同步阻塞改造、MACD 算法升级、备份系统、Paper/Broker。相关测试只用于证明本轮没有改变这些边界。

## 9. 验证设计与当前实际证据

### 9.1 后续实施的测试矩阵

| 主题 | 必需样例 | 主要既有测试入口 |
| --- | --- | --- |
| 区间/分页完整性 | 同日内缺、头尾缺、跨页缺、跨月整分区缺、完整窗口、休市、history floor | `data_foundation/test_catalog_and_service.py` |
| 期货端点 | 午夜、周末、长假、无夜盘、短尾60m、W1短周、周中换月、上市/到期 | `data_foundation/test_aggregation.py`、`test_infrastructure.py` 及 coverage/replay 测试 |
| 来源身份与交易日 | 错合约、缺身份、错 trading_date、合法日超集、重复/冲突、错批、夜盘单点参数 | `data_foundation/test_infrastructure.py`、`test_historical_data_manager.py` |
| 原子发布与更正 | 后半批无效导致零发布、授权 refresh、范围外覆盖失败、Bar/quality冲突、部分IO失败保留既有恢复边界 | `data_foundation/test_historical_data_manager.py` 及 D1 quality 测试 |
| 统计 | 换月价差/OI差、同合约 warm-up、历史T不受未来切换影响、NO_TRADE断点、不足、旧投影拒绝 | `data_foundation/test_market_home_overview.py`、`test_market_research.py`、`test_market_home_projection.py` |
| 健康 | 单品种/单周期停滞、先漏后到、无信号、午休/夜盘、盘后等待、重启、旧heartbeat、Scope变化 | `test_runtime_health.py`、`test_alert_runtime.py` 及 Live tests |
| 消费者与不回归 | 单品种降级不熄灭正常报价、类型parser、projection miss、Newow D1断段、Alert/replay完整性、Event one-shot | 相关 API/Web、Newow 与 Alert 定向测试 |

完整性测试使用临时 SQLite/Catalog/Parquet 和真实 MDS 读取，不只 mock 校验器返回成功；provider 参数与故障测试用 fake provider，保证无外部调用。需要验证 PostgreSQL 隔离行为时使用隔离测试库，不能指向 production。

性能以相同输入的改造前后读取次数、分区数和端点数比较为第一道确定性检查；60 品种离线压力测试要证明查询按请求窗口和 Scope 有界，不以一次快速 mock 证明生产性能。实际工作站读取延迟、重启后逐品种推进与自然盘后闭环属于后续受控 Runtime 验收。

### 9.2 本轮已执行

在本设计工作树运行以下基线命令，结果 **487 passed in 6.12s**：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:///:memory: \
PYTHONPATH=services/quant-api:packages/quant-core \
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python \
-m pytest -q -p no:cacheprovider --tb=short \
services/quant-api/tests/data_foundation/test_aggregation.py \
services/quant-api/tests/data_foundation/test_infrastructure.py \
services/quant-api/tests/data_foundation/test_catalog_and_service.py \
services/quant-api/tests/data_foundation/test_historical_data_manager.py \
services/quant-api/tests/data_foundation/test_market_home_overview.py \
services/quant-api/tests/data_foundation/test_market_research.py \
services/quant-api/tests/test_runtime_health.py \
services/quant-api/tests/test_alert_runtime.py
```

另在临时 Catalog/Parquet 上复跑同日缺分钟最小复现，普通查询与分页仍各返回 2 根而不是拒绝。这是问题持续存在的证据，不是修复验收。临时脚本不是正式交付测试；实施 A 时须把该行为固化为仓库回归。

本轮文档验证包括路径/符号核对、设计边界自审和 `git diff --check`。没有运行实现后的新测试，没有验证真实 RQData、生产数据完整率、用户收件或 Runtime 自然闭环。

后续前端改动至少运行相关 `node --test`、`pnpm -C apps/quant-web build` 及定向 API tests；具体模块测试按上述矩阵扩展，不为了形式重复运行无关全仓测试。

## 10. 发布、恢复与 owner 审阅点

A/B 代码会使过去静默通过的数据显式失败。发布前应对 operational 品种与实际消费周期做固定窗口只读清点，列出受影响项；不能为获得全绿自动补数。任何真实下载/Canonical或数据库写入另给精确范围和授权。

C 改变通用统计输入口径，必须确认“目标日主力的同合约历史，允许成为主力前 warm-up”的产品选择，同时确认 NO_TRADE 的通用价格指标断点策略；不需要改变 Newow 公式。旧投影与旧前端缓存按版本失效，保留旧产物可核对，不由 GET 执行删除。

D 只新增有界 heartbeat 覆盖字段；当前 Runtime 不切换就不会产生逐项证据，新 API 应显示 unverified。升级与回退必须测试旧/new heartbeat 组合，旧 reader 不认识新增字段时不能带病发布；通知持久状态 schema 6 不变。旧版本回退可能恢复旧健康语义，应在 owner 视图明确本版本未提供逐项覆盖，不能把回退当问题已解决。

代码集成、main/tag/release、Runtime promotion、生产数据修复、自然业务验收分别记录。当前设计不执行任何一个外部 Gate。既有运行服务、Scope、通知和自动任务不因本文变更。

建议审阅通过后，最小下一步是实施 A：统一 MDS 窗口完整性，并把已复现的缺分钟场景变成正式回归。A/B 完成且受影响范围清楚后，再决定数据修复批次与 Runtime 发布窗口。
