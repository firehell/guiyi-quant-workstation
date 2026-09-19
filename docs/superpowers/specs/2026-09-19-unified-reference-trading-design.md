# 统一参考交易：持久化、增量计算与盘中观察设计

日期：2026-09-19。状态：设计提案；owner 已认可统一方向，本文件细化实现合同，不声明实现、迁移、发布或启用完成。

调查基线：develop `8aef4c2b7875d7a8aa5b7fe13344ead1ea669cf4`，调查开始时主工作树干净。
其他任务仍在推进苏冰四周期、牛哇周期开放和发布；实施前必须重新核对 develop 依赖、当前 capability 和 Runtime。
开发步骤见 [implementation plan](../plans/2026-09-19-unified-reference-trading-plan.md)。

## 1. 目标与明确不做的事

建设一个所有策略共用的 Reference Trading 应用模块：历史首次构建、后续增量维护、持久化、统一查询、版本核对和故障恢复。
策略分别提供既有公式、动作及参考价格，页面不再承担完整历史回放。后台在无人访问页面时也可维护已启用范围。

用户最终按“策略 / 品种 / 周期 / 记录口径”查看信号、OPEN/CLOSED/中断交易、固定窗口统计、数据截止与健康状态。
同一周期的数据与策略状态独立于其他周期，不要求多个周期同时开仓或等待彼此完成。

这不是模拟账户：不生成订单、Fill、资金、保证金、手数、账户 PnL、风险分配或真实交易；`executable=false`、`auto_order=false`。
不改变现有牛哇、苏冰公式、参考价格和收益算法，不把 Hint、照妖镜或比较器动作提升为正式参考动作。
不自动扩大 Alert Scope、收件人或通知次数；参考交易成功不等于预警发送，发送失败不影响参考记录。
不恢复已退役的 Historical Projection、策略 Event 表及对应旧 API。使用新的领域身份和新表。

## 2. 当前实现依据

| 现有入口 | 已有能力 | 本次处理 |
|---|---|---|
| `packages/quant-core/guiyi_quant/newow/reference_trades.py` | 纯 Decimal 配对、同 Bar 顺序、OPEN/CLOSED、中断 | 提取可增量执行的相同规则，保留全量入口作为同一算法的 fold |
| `packages/quant-core/guiyi_quant/newow/reference_statistics.py` | 固定窗口、期初交易、统计口径 | 复用算法；窗口归属是查询结果，不写死到交易身份 |
| `services/quant-api/app/market_data/newow/product_service.py` | 请求时 replay/project/statistics | reference section 改成读取统一结果，其他 section 按既有实现 |
| `services/quant-api/app/market_data/newow/snapshot_cache.py` | 默认 300 秒、进程内有限缓存 | 可保留轻量响应缓存，不承担持久化与正确性 |
| `packages/quant-core/guiyi_quant/subing_reference.py` | 双向反手、信号 Close、纯投影 | 接入统一模块；保留四周期工作已确定的版本与缺价合同 |
| `services/quant-api/app/market_data/subing_reference.py` | MDS 输入、历史计算、分页 | 历史数据读取供后台；GET 改读结果 |
| `services/quant-api/app/alerts/evaluators.py` | HTDY first_seen / SuBing exact | 复用纯评价规则，不调用发送入口，不共享 Event 写入事务 |
| `packages/quant-core/guiyi_quant/indicators/htdy_original.py` | future dependency 24 Bar、repaint scan 27 Bar | 保留 observation-only；不能当非重绘策略接入 |
| `services/quant-api/app/market_data/market_home_projection.py` | 首页派生文件、原子替换 | 仅借鉴结果与事实分离，不把首页缓存扩成交易数据库 |

当前四周期苏冰仍需以实际集成提交核定；不能把工作分支、当前 develop 或已发布标签混作一个版本。
外站通过接口查询只能证明交互形式，不能证明其后端持久化或增量算法。

## 3. 两种记录口径

### 3.1 `historical_replay`：可重建的历史参考

- 输入为经过校验的 Canonical，经 MDS 读取；记录固定输入版本、公式、参考模型和截止时间。
- 未变化历史只计算一次；新增可信 Bar 增量推进。修订发生时构建新的结果 revision。
- 用于牛哇三策略、苏冰的历史研究。默认完成交易日合同不因本次重构而放宽。
- 不能补写 AlertEvent、盘中首次观察或通知。

### 3.2 `forward_observation`：启用后实际观察的参考

- 输入为通过现有 Live 读取与完整性校验的 completed 数据；不把 Live 晋升为 Canonical。
- 保存实际 `observed_at`、`processed_at`、Bar 时间、交易日、物理合约、source kind 和消费证据。
- 观察动作不可因事后重绘或盘后源数据修订被删除、改时刻、改方向；参考交易本身仍按后续动作演进。
- 可以由保存的观察事实重建交易投影；观察事实自身不是可删除缓存。
- 停机期间未观察到的历史 Bar 不补造 first_seen。迟到数据仅用于恢复状态或独立历史核对，不冒充当时观察。

两类结果共用代码与查询能力，stream identity 必须不同。页面分别统计，不能拼接成一条收益曲线。
新启用 forward 流默认 `FLAT + recording_start`，历史 OPEN 不携入；允许历史输入预热指标，但预热不生成 forward 动作。
启用时策略可能已处于 HOLD；随后 CLEAR 仍保留源动作，但公共投影记 `NO_OBSERVED_ENTRY`，不制造零收益交易。
这不等同牛哇须有完整生命周期证明的 `INITIAL_CLEAR_NO_ENTRY`，不能改写源动作标签。
首版启用政策固定为 `forward_flat_start_v1`，纳入 observation_policy_version，历史模型不因此变化。
若未来要继承历史 OPEN，需要另立带 `INITIAL_CARRY` 的参考模型和起始统计合同，不在首版实现。

### 3.3 HTDY 的首版边界与模型提案

当前 HTDY 明确 `historical_backtest_allowed=false`，首版历史图继续回看，但不新增基于重绘历史的收益/交易流水。
HTDY 接入统一模块的首个目标为 `forward_observation`，不宣称补齐全部历史交易。
既有 AlertEvent 缺少完整公式/输入证据的，不批量导入为新模块的过去交易；首版从明确启用时刻记录。

新模型提案 `htdy_first_seen_reverse_close_v1`：

- 只消费既有 first_seen 政策允许的最新 completed Bar 单方向观察；保持 observation-only。
- 第一个 buy 开多、sell 开空；同向无加仓；反向按信号 Bar Close 结束旧参考并开始新参考。
- long return = `(exit - entry) / entry * 100`；short return = `(entry - exit) / entry * 100`；Decimal，零费零滑点。
- 同 Bar buy/sell 冲突不猜顺序：保存冲突诊断，阻塞该流；不制造任一方向交易，也不推进有效计算水位。
- 参考价同时保留 `reference_price_at=bar_end` 与真实 `observed_at`，不暗示该价在观察时仍可成交。

这是新业务模型，不是现有 HTDY 已具备的合同。其规则需在实施阶段 P0 明确接受后方可生成参考交易；
公共模块、牛哇与苏冰可独立推进，HTDY 默认 `MODEL_NOT_APPROVED`，不得静默套用苏冰模型。
HTDY 若未来建设历史回看交易，须另立 retrospective 模型、重绘修订和收益展示合同；不以有限回看重算包装因果回测。

## 4. 模块与调用关系

```text
Canonical -> MDS historical reader ----+
                                      +-> Strategy Adapter -> Reference Reducer
completed Live -> validated reader ---+                           |
                                                                 v
                          Coordinator -> PostgreSQL atomic commit
                                                                 |
                                              Query -> API -> Web

既有 Alert evaluator/service/transport 独立运行，不由 Reference 调用。
```

### 4.1 Strategy Adapter

每个适配声明策略身份、可用周期、口径、公式版本、参考模型、预热需求、checkpoint schema、是否重绘及评价规则。
周期是否能读取、是否已验证、是否对页面开放、是否持续计算，分别表达，不能从一个 capability 推导另一个。

适配消费有序输入和自身计算状态，产出有序 `ReferenceAction`、指标状态与诊断。公共模块不得重写策略公式。
Action 分为 `OPEN_LONG/OPEN_SHORT/CLOSE/HINT`；反手由同 Bar 两个有序动作表达，必须显式绑定被关闭的 entry/action identity。
Hint 的 `quantity_effect=none`；不为兼容未来账户而引入比例仓位、REDUCE 成交或手数。
每个 action 含 source signal id、Bar 时间、sequence、参考价及价格类型、owner/calculation segment。

### 4.2 Reference Reducer

无 IO 的纯函数，负责同流、同物理合约、同计算段内的精确关联、状态迁移和参考估值。
全量投影与增量调用同一个 reducer；全量入口是逐项 fold，不能长期保留两套公式实现。
策略参数化差异由 adapter/model policy 提供，不在查询或存储层堆叠策略分支。

### 4.3 Coordinator / Repository / Query

- Coordinator 负责读取进度、输入校验、调用计算、构建批次和提交；不负责 provider 下载。
- Repository 负责事务、唯一约束、revision 发布、快照查询；不计算指标。
- Query 负责过滤、固定口径统计、分页和状态；GET 不写 DB、不下载、不调用完整历史回放。
- 单个现有部署体系内的 reference worker 是首版写入者，默认关闭；不引入微服务、消息中间件或额外数据库。

## 5. 身份、时间和版本

`stream_id` 由以下规范字段构造，不能含页面窗口、分页位置或运行进程 ID：

```text
strategy_code, formula_versions, profile_id, reference_model_version,
futures_adaptation_version, product, frequency, series_kind,
recording_mode, observation_policy_version
```

一条 stream 可跨多个真实 owner 段，但一笔交易不得跨物理合约、owner/calculation segment 或模型版本配对。
已有 source signal/trade ID 在各策略回归中保持稳定；通用存储键在其外加 stream namespace，不强行重编旧公开 ID。
相同 Bar 允许多个有序动作，不能使用 `(symbol, frequency, bar_end)` 作为全模块动作唯一键。

- `revision_id`：一次固定规则下的历史重建/投影修复代际；新公式建立新 stream。
- `commit_seq`：同 revision 内单调提交序号，绑定动作、交易变化、估值和 checkpoint。
- `bar_end / trading_day`：来自权威 Session/Calendar，不能由本地日期截取推导。
- `observed_at / processed_at`：首次观察与实际处理时间；历史 replay 不伪造 observed_at。
- `computed_through`：已连续处理的最后有效输入；有信号与否都推进。
- `expected_through`：按周期完成条件与输入发布事实计算，休市不要求凭空有新 Bar。
- `canonical_confirmed_through`：已与 Canonical 核对的 forward 边界，不等同 computed_through。
- `input_snapshot_hash / dependency_manifest`：含行情、映射、Session、质量、预热及公式依赖。

状态区分 `DISABLED/NOT_BUILT/BUILDING/READY/LAGGING/BLOCKED/STALE_INVALID`；
质量维度另表述 `FULL/PARTIAL/UNAVAILABLE`。无交易且 ready 才是正常空列表，数据不足不是空列表。

## 6. PostgreSQL 存储设计

复用现有 SQLAlchemy / Alembic / PostgreSQL。以下均为拟新增表，不复用 AlertEvent 或退役表。
价格和收益用无隐式舍入的 PostgreSQL NUMERIC；API 序列化 Decimal 为字符串。非数/非法价格拒绝。

| 表 | 主要字段 | 约束与用途 |
|---|---|---|
| `reference_streams` | identity 字段、enabled、activation_at、active_revision_id、latest_seq、health、row_version | identity unique；activation scope 独立于 Alert；所有流默认 disabled |
| `reference_revisions` | stream_id、revision_id、status、reason、parent_revision、input identity、published_seq | candidate/active/superseded；发布为短事务指针切换 |
| `reference_batches` | stream_id、revision_id、seq、batch_key、outcome、input range、dependency manifest、pre/post state、state schema、observed/processed time、evidence | committed 批次 seq 非空且 unique revision+seq；stream+batch_key unique；诊断批次 seq 为空且不推进有效 checkpoint |
| `reference_actions` | stream_id、source_action_id、revision_id、sequence、bar/observed time、segment、kind、price、links、batch_seq | 唯一动作身份；forward source action 不覆盖，历史动作按 revision 保存 |
| `reference_trades` | stream/revision、trade_id、entry/exit action、side、status、prices、return、segment、valid_from_seq、valid_to_seq | PK revision+trade_id+valid_from_seq；任一 seq 下单一有效版本；跨流/段关联校验 |
| `reference_marks` | stream/revision、trade_id、bar_end、trading_day、mark price、holding_bars、mark_return、batch_seq | 仅有 OPEN 或状态变化时写估值；支持历史截止查询，不覆盖为最新一个值 |

`reference_batches` 首版合并批次、checkpoint、输入证据和失败诊断，避免另造作业平台。
查询索引至少覆盖 stream identity、revision+seq、trade entry 倒序、action Bar 顺序、trade mark 截止、batch_key。
跨表外键必须包含所属 stream/revision，不能仅检查一个全局 ID 存在。
forward 的 source action 身份在 stream 内唯一；投影修复引用原动作所属 revision，外键验证相同 stream、mode 和版本，
不复制成新的观察动作。historical action 在各 revision 内唯一。repository 须显式区分这两种关联规则。

### 6.1 输入证据的持久性

Historical batch 保存 Canonical dependency manifest；输入修订后允许旧历史 revision 失效并重建。
Forward batch 保存实际消费的 completed 周期 Bar 数值、源身份/完整性证据、评价起始状态与 schema、动作和状态 hash。
初始化把必要计算状态完整保存；HTDY 等窗口型算法还保存实际使用的有界评价窗口。
共享的大块预热输入在初始化批次分块保存，末块验证整体 hash 后才允许激活；不把巨量 JSON 放进一个长事务。
后续可通过初始化 checkpoint + 持久输入 delta 重放观察后的计算；不能仅用可能被覆盖的 Canonical 路径或过期 Redis key 作为恢复依据。

这些数值是“当时消费者看到了什么”的证据，不成为第二套行情查询入口；行情 consumer 禁止读它们替代 MDS。
未获授权的 provider 补数不属于恢复路径。证据保存失败则该批不提交成功，不允许仅存交易而丢观察证据。

### 6.2 版本与保留

普通新 Bar 不复制整个历史：新增 batch/action/mark；交易仅在开、平、中断等状态变化时新增行版本。
一次历史修订可在受影响 stream 的 candidate revision 中复制未变结果、重算受影响尾部，校验后原子发布；不全站重算。
旧 revision 首版不自动删除。动作、batch 和观察证据不做 TTL 缓存清理。
实施测量实际行数和容量后再制定保留/压缩策略；删除或归档不作为首版隐含任务。

## 7. 首次历史构建

1. 冻结 stream 范围、历史起止、源 revision 与目标截止，生成只读 dry-run 清单。
2. 通过 MDS / 既有研究 reader 确认 rank1 owner、物理生命周期预热、Calendar/Session 和 coverage。
3. 从适配所需起点计算，预热区不生成 owner 外交易；显示窗口不裁剪预热。
4. 分块写 candidate revision，每块保存进度和输入 hash；候选不对正式查询可见。
5. 全量对照现有 projector：动作、交易 ID/价格/状态、期初归属、统计完全一致。
6. 发布前再次校验依赖未变；变更则废弃候选并报告，不发布混合快照。
7. 短事务切换 active_revision，写入完成截止；重启从已验证块恢复。

某个 stream 构建失败不阻塞其他品种；不能将失败项写成零交易成功。总报告明确全部、完成、阻塞数。

## 8. 增量事务和并发

```text
读取 stream revision/seq + checkpoint
  -> 获取该流缺少的连续、已完成、身份有效输入
  -> 校验旧依赖，计算纯 transition（事务外）
  -> 短事务锁 stream 行，核对 revision/seq/row_version
  -> 写 batch / actions / trade versions / marks / checkpoint
  -> 更新 seq 与 computed_through
  -> commit
```

所有新结果同一事务可见。revision/seq 变化则拒绝旧候选，重新读取；不覆盖另一个 writer 的结果。
`batch_key` 由 stream、源输入身份、前序水位与目标范围确定，确定性去重。
相同身份相同内容重放为 no-op；同身份不同内容是 conflict，不能用 upsert-last-wins 掩盖。
提交结果未知先只读按 batch_key 核对，确认未提交且仍在授权恢复次数内才重试。
普通开发测试可重跑；正式持续写入的重试边界随 activation 明确，不由此设计自动授权。

单进程首版一个计算 worker；同输入批可共享 validated read，策略状态分别维护。每个 stream 轮转，避免慢品种饿死其他流。
内存唤醒队列有界，合并相同 stream 的唤醒提示；消息只是唤醒，不能把丢 Pub/Sub 当作已经处理。
启动与周期性扫描核对 source watermark / persisted watermark。无耐久输入证据的停机区段按第 10 节处理。
每轮时间、Bar 数与内存预算由基准测量确定并写配置；超预算保持水位和旧有效快照，不吞掉输入、不无限排队。

## 9. 盘中完成条件与期货特有场景

| 情况 | 必须行为 |
|---|---|
| 15m/30m/60m | 复用 authoritative Session buckets 和完整 1m 输入要求；不自行整点 resample，不跨休市补 Bar |
| D1/W1 | historical 使用正式 Canonical 来源；盘中临时聚合不冒充 D1/W1 Canonical。未具备独立 completed 读取合同的周期，forward 返回 capability unavailable |
| 夜盘跨午夜/周末/节假日 | 交易日以 Calendar/Session 为准；记录实际 instant，不把周五夜盘简单归周六 |
| 午休/短尾桶/不同收盘时刻 | 仅按既有 Session 合同处理，不静默丢尾桶或等待整点造成错过信号 |
| 主力切换 | 同一交易日/Bar 使用权威 rank1；旧 OPEN 变 ROLLOVER_INTERRUPTED，无伪造 exit price；新物理合约独立预热 |
| 旧合约迟到数据 | 不污染新 owner 状态；只用于相应历史核对，不能倒退当前水位 |
| 同合约退出后再成为主力 | owner segment 重新识别，不把两次 owner 拼成持续持仓 |
| 正式已证明 PRICE_UNAVAILABLE | 沿已有质量合同形成 DATA_INTERRUPTED、保留 CLOSED，重置计算段并重新预热 |
| 未知缺口/重复冲突/映射未知 | BLOCKED，禁止跳过、填值或伪造 DATA_INTERRUPTED 证明；补齐/厘清后按恢复合同处理 |
| 涨跌停/零成交量 | 继续使用既有输入质量与模型规则；参考价不证明可成交，不悄悄加执行撮合规则 |
| 同 Bar 多动作 | 按策略声明 sequence，先结束后开启；明确关联，不能搜索最近开仓 |
| 相同信号反复出现 | 相同身份幂等，同向不加仓由 model 决定，不能因通知重复而重复交易 |
| 历史改变/公式升级 | 源修订新 revision；公式/收益/模型变化新 stream。不得覆盖旧观察动作 |

分钟级 capability 与 D1/W1 capability 独立验收。架构支持七周期不等于七周期均可立即盘中记录。

## 10. 重绘、历史修订、断线恢复和盘后核对

### 10.1 非重绘的历史增量

牛哇可参与参考的主动作和苏冰分别证明 prefix invariance、batch/incremental parity、checkpoint restart parity。
算法若不能有界恢复状态，先提供经证明的 bounded replay adapter；不能宣称已做到每 Bar O(1)，也不能以任意短窗口代替完整预热。
技术债出口：历史前缀不重复计算；增量成本与新增数据/声明回看窗口相关，不随全历史无限增长。

### 10.2 历史依赖修订

从最早受影响输入之前的有效 checkpoint 重算后续，不只重算修订当天。EMA 等递归影响可一直延伸至最新。
预热、映射、Session、质量与公式依赖均参与失效；不能只比较最新一根行情。
有可靠 dependency revision 时用 manifest；若上游不能定位最早变动，就重建受影响物理计算段或整个 stream，不能猜安全起点。
旧结果已知失效标记 STALE_INVALID，正式查询不能仍宣称有效；未受影响流继续服务。

### 10.3 停机与迟到

- 已耐久捕获、尚未投影的输入：恢复时使用原 observed_at 和输入证据，幂等完成，不重发通知。
- 未捕获但 Canonical 后来有数据：只能补 historical；不能补写 HTDY first_seen。
- forward 缺失区间：保存 observation gap，历史可能完整但 observation coverage 不完整；不能沿用旧 OPEN 穿越未观察区间。
- 明确确认无法恢复后，将旧 OPEN 标记 `OBSERVATION_INTERRUPTED`（新的通用状态），不填 exit price/return；
  重新建立有明确起点的观察计算段、预热后从 FLAT 继续，累计统计披露中断区间。
- 是否继续属于 activation 的既定恢复策略；首版默认阻塞并等待明确恢复，不自动扩大输入范围。

### 10.4 盘后

Canonical 发布成功后给 reference worker 一个唤醒提示；周期性对账弥补提示丢失。
不把全策略构建塞进 after-market 维护锁；worker 按现有读取/维护互斥合同取固定输入快照并复核。
reference 更新失败不回滚成功的行情发布，也不使行情已成功事实变失败；独立 health 暴露失败。
核对 forward 实际输入与 Canonical：一致写核对记录；不同保存差异，historical 生成新 revision，forward 原观察不改。
不合并两类收益；任何 retrospective 重绘结果不替换当时记录。

## 11. 统一查询与页面合同

拟新增接口（正式路由名在 P0 canonical 中冻结）：

```text
GET /api/v1/reference-trading/capabilities
GET /api/v1/reference-trading/streams?strategy=...&product=...&frequency=...&mode=...
GET /api/v1/reference-trading/streams/{stream_id}/trades?since=...&through=...&limit=...&cursor=...
GET /api/v1/reference-trading/streams/{stream_id}/signals?since=...&through=...&limit=...&cursor=...
GET /api/v1/reference-trading/streams/{stream_id}/summary?since=...&through=...&snapshot=...
```

首次列表响应含 `revision_id/commit_seq/snapshot_token/computed_through/expected_through/recording_start/coverage/status`。
snapshot token 与 stream、revision、seq、窗口和统计政策绑定，opaque 且不能越权组合；非法参数显式拒绝。
后续 signals/summary/分页必须引用相同 snapshot；同一快照下用 trade validity interval 和 marks 截止选择结果。
并发追加不能改旧页的 OPEN/CLOSED 状态；历史 revision 被标失效返回 `SNAPSHOT_INVALIDATED`，不能悄悄换页。

支持查询已保存覆盖范围内的历史截止，返回实际可用 Bar 截点；当时 OPEN 使用对应 mark，不使用今天的退出状态。
historical 截止表示所选数据 revision 下的研究结果，不保证当时已知；forward 回看同时约束 Bar 与 observed_at 截止。
批次里晚于查询截止的观察不能因 Bar 时间较早而泄漏到过去结果。
超出范围明确拒绝或报告未构建，GET 不临时补建。初版 limit 1..200；无过滤全站大列表不提供。
统计沿各 reference model 的政策，固定日期窗口、期初归属、简单累加/复合等不得因统一而改变。
不提供跨模式、跨策略、跨周期的账户式总收益；不同模型结果可并列比较，不能直接相加。

前端共用查询 composable、分页、状态、来源和通用交易表；标签、参考价说明和策略 Hint 由各策略适配。
牛哇 reference section 的图表/信号/交易必须核对同一输入身份；reference 滞后时提示不同截止，不能装作对齐。
15m AlertEvent 点击仍按 Event 精确 focus；参考页定位找不到对应记录时显示原因，不从预警补造交易。
首次未构建显示 NOT_BUILT；更新滞后显示上次有效截止；已知失效显示不可用，不以静默全量重算作为 HTTP fallback。

## 12. 配置、性能和上线

能力注册在代码，启用范围保存在 reference_streams；不复制 active/operational 品种事实。
historical 产品范围服从各策略研究 capability；forward 还必须属于现有 Live 数据可支持范围。
首版默认全部 disabled，bootstrap/enable 分开；仅查询不激活任何流。

阶段迁移：旧计算输出对照 -> 隔离构建 -> 只读 API/Web 验证 -> 批次批准生产 schema/bootstrap -> 查询切换 -> 精确 scope 启用 worker。
查询切换按策略/周期为单位，不做随机流量双写；旧 GET 暂作统一 reader 的薄适配，迁移完成删除重复计算入口。
保留纯全量计算作为 rebuild/reference oracle；不是第二套运行中的 HTTP 回退。

回滚先停 worker 并读回最后提交位置，关闭新 reader feature switch；保留表、动作和证据，不 downgrade 删除生产表。
旧页面若需要恢复，只能明确切回兼容旧版本的历史计算路径，且不能声称展示 forward 记录；不删除新记录以迎合旧版本。
运行版本切换、schema、生产 bootstrap、scope enable 和通知保持各自授权边界；本设计不批准这些实际操作。

性能验收以固定数据量、同硬件基线进行：查询代码路径无 replay；索引分页；增量不重复历史全量；内存与队列有界。
至少测单流、同周期 60 品种、多策略组合以及大历史修订；记录 p50/p95、处理延迟、峰值内存与 DB 增长，不预先虚报数值。
生产容量预算在 activation 前形成明确 scope、历史跨度、每流预算与失败策略，不根据“全周期支持”推导无限任务。

## 13. 完整验收出口

1. 现有牛哇和苏冰 golden 逐字段一致，reference ID 与统计窗口语义不变。
2. 固定输入全量、随机切批、逐 Bar、checkpoint 重启结果相同；HTDY只对相同观察输入序列验证，不拿最终重绘结果比较 first_seen。
3. 重复输入 no-op；身份冲突拒绝；两 writer、commit 前/后 crash、提交结果未知无重复无水位跳跃。
4. 夜盘/节假日/短桶/换月/缺价/未知缺口/重新预热/旧 owner 迟到有真实规则 fixture。
5. 历史依赖修订、新版本、新 snapshot 并发查询不混代；旧窗口 mark 不偷用未来 exit。
6. PG 隔离库实际验证事务、NUMERIC、唯一/FK/约束、MVCC 查询和迁移；SQLite 替身不替代这些证据。
7. Redis/通知连接断开不会让 historical query 失败；Reference 写入不触发 AlertEvent/transport。
8. HTDY冲突、重绘、观察缺口、没有历史补造与默认禁用有负向测试。
9. API/Web 开关切换、旧接口薄适配、来源标识、空列表与未构建、取消/分页/策略切换通过。
10. 生产 enable 后另验自然 completed Bar、无信号推进、有信号更新、盘后核对和故障健康，不用测试结果代替自然证据。

## 14. 实施前必须冻结的业务项

- 接受本文件 HTDY v1 的具体参考模型后才实现其交易生成；否则保留 capability blocked，其他策略正常推进。
- HTDY首版不提供重绘历史交易收益；所有 forward 从显式启用时刻 FLAT 开始，不携入旧历史 OPEN。
- `OBSERVATION_INTERRUPTED` 为新的参考记录状态，原牛哇/苏冰历史状态及版本不因此重写。
- 数据源、策略、收益变化走独立版本；生产启用范围由实际 capability 和验收决定，不在设计阶段猜定全量矩阵。

上述默认方案已完整给出，P0 将其写入新 canonical 并标清接受状态，不用未决占位条款让后续实现自行猜测。
