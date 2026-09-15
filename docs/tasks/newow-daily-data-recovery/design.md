# 牛哇日线数据完善：差量恢复与验收设计

日期：2026-09-15。原始设计基线：`develop@d653a8c864f5f09d98309357f64ab16dde87eb2d`。
本次补充与计划核对基线：`develop@c9ed8ec503bda9287f4b77967854a3d696c8014b`。

本次交付为设计文档、[Implementation Plan](implementation-plan.md) 及[设计审查记录](review.md)，
不是实现、数据恢复或产品开放结果。Owner 本轮明确要求补充设计、编写计划、Review 后直接在 develop
commit/push；该授权仅覆盖文档交付，不启动恢复代码实施。
实施前须确认本方案，真实 RQData 查询/下载、Canonical/生产 DB 写入仍需新的精确单次执行意图。
未读取本地生产 Catalog、Parquet 或共同证据根，日线缺口数量、预计耗时和当前周线余额均未测定。

## 1. 目标与范围

目标是让个人操作者以一次固定范围的任务完成日线依赖盘点、普通缺数恢复和统一结算，
不再手工挑合约、组织每批命令或拼接验收日志。内部仍然有界分批，必要校验不减少。

本设计只处理牛哇三策略的 completed `actual_dominant / 1d` 所需物理合约日行情，
以现有 operational 品种集合为默认盘点范围，并校验它属于 active、non-retired 范围。
这不是新的 Runtime Scope；两个 universe 文件均不修改。首轮执行范围由完整原生审计形成，
不把周线历史成功数量、旧候选列表或手工排除名单作为日线剩余范围。
可用性只承诺冻结的 consumer 与窗口；未枚举的任意历史快照/自定义范围不能被写成已验收。

消费范围包括主图、同周期副图、ReferenceTrade 所需生命周期前缀及其 owner 区段。
独立比较器须核对同周期真实输入，但样本/研究证据不足不自动成为补数目标。
完整跨周期 explanation、60m、公式/评分/参考价修改、账户/订单、发布与 Runtime 均不在本轮。
现有 dependency 枚举未单列 comparator；实施时须通过真实 service/reader 证明其所需窗口被已枚举
D1 依赖覆盖。默认比较器在 `product_service` 的窗口解析与 `_comparator` 路径中复用主图的
`reader.load` 结果，消费同一 `replay_bars/owners`，未发现独立行情下载窗口；这只是源码证据，
仍须验证同一 as_of、owner 和实际前缀。显式 since/through、自定义窗口和历史翻页不自动纳入默认承诺。
若不能证明，保留该面板待验，不用主图数据就绪替代比较器验收，也不在 wrapper 另造窗口算法。

最终分别交付三个事实：

- 盘点是否完整：所有本次依赖都有明确结果，没有被超时或未知状态隐藏的范围。
- 恢复是否完成：冻结普通目标实际完成了多少，哪些仍被异常、失败或未尝试阻塞。
- 日线输入是否可用：各品种、各消费模块能否用真实 reader 严格读取；不等同于 typed API/Web 已开放。

## 2. 基线事实与设计依据

| 已核对事实 | 现有权威/实现 | 对本设计的约束 |
|---|---|---|
| D1 是交易所日行情；W1 来自同源完整 ISO 周 | [DATA_CENTER](../../DATA_CENTER.md) | 不用 settlement、其他日线接口或跨频数据替代 |
| 原生 warm-up 已支持显式 `1d`，只含 D1；省略频率是七周期 | [维护合同](../../../openspec/specs/historical-data-maintenance/spec.md)、[manager](../../../services/quant-api/app/market_data/historical_data_manager.py) 的 `_contract_warmup_scope` | 必须显式绑定 `1d`，不能误用默认七周期 |
| 日常 `mode=daily` 与日线 `frequency=1d` 不是同一概念 | [DATA_CENTER](../../DATA_CENTER.md) 的更新合同 | 不拿盘后 daily-recovery 代替历史日线 warm-up |
| readiness 按真实 reader 窗口、owner 和 consumer 枚举并合并修复需求 | [readiness](../../../services/quant-api/app/market_data/newow/readiness.py)、[product_reader](../../../services/quant-api/app/market_data/newow/product_reader.py) | 不再建文件数量/首尾日期式缺口探测器 |
| 周线子执行器虽称 W1/D1，`_validated_unit` 和 `_zero_commit_readback` 仍固定 `1w` | [子执行器](../../../scripts/newow_weekly_recovery.py) | 不能改一个命令参数就宣称支持 D1 |
| campaign 报告合同限定 `frequency_scope=[1w]`，并绑定 weekly release stage | [总包编排](../../../scripts/newow_weekly_recovery_campaign.py) | D1 必须有独立 schema/profile 校验，旧 W1 包不能解释成 D1 |
| readiness matrix 始终建立三策略×三周期；未开放周期为 UNOPENED | [readiness](../../../services/quant-api/app/market_data/newow/readiness.py) | D1 dependency-only 审计与 public matrix 分开，不能要求本轮日线 API READY |
| 当前 typed 产品仅开放 W1；旧 trend-detail 固定 D1 是独立兼容面 | [product_release](../../../services/quant-api/app/market_data/newow/product_release.py)、[PROJECT_SOURCE](../../../PROJECT_SOURCE.md) | 不修改能力开关，不借兼容入口证明三策略日线全部可用 |
| Canonical 原子单位是单个月分区，不是整合约或总包 | [DATA_CENTER](../../DATA_CENTER.md)、[DECISIONS](../../../DECISIONS.md) | 部分提交和结果未知必须如实保留，不能承诺全局回滚 |

工程授权、事实源和串行维护边界分别沿用 [AGENTS](../../../AGENTS.md)、
[DEVELOPMENT](../../DEVELOPMENT.md)；当前阶段只看 [STATUS](../../../STATUS.md)。
本设计不修改上述 active canonical，不将建议伪装成已接受业务合同。

## 3. 方案选择

采用“复用原生 D1 planner/writer，给现有恢复编排增加一个封闭的日线 profile”。

不采用手工循环调用每个合约：底层能力虽已具备，但操作者仍需负责去重、批次、失败和结算。
不新建通用 ETL/任务平台：现有日周两类用例只需要明确 scope，不需要插件注册、任务 DB、
后台 worker、消息队列、自动恢复服务或另一套数据完整性事实。

保留现有周线入口和历史包语义；D1 新包使用新的明确 schema 身份。只允许两个已定义范围：
`1d -> [1d]` 和既有 `1w -> [1d,1w]`。本次不顺带支持 60m，亦不为其预建泛化框架。
后续分钟数据仅复用经验证的编排/结算概念，仍需独立来源与聚合合同。

“全合约来源一次预校验后再发布”列为后续可选优化，不作为日线首版前置：
当前 manager 已在来源请求组内先校验再发布，扩大预取范围会改变资源、锁和部分提交路径。
本轮不新建 staged-source 导入器或第二个 publisher；只有真实 D1 运行证明这项优化有必要时，
再按独立有界设计评估。不能为优化未知瓶颈继续推迟普通补数。

## 4. 用户流程与执行边界

一个入口完成“读取完整原生审计 -> 自动 prepare 全部子包 -> 汇总精确范围”。
Owner 批准本次精确总包后，前台单进程连续执行正常内部批次并统一结算。
失败退出后只允许只读对账和准备新剩余包，不自动 resume/retry；新执行仍须新意图。
具体可执行命令在实现时集中写入 [TESTING](../../../TESTING.md)，本文不提供尚不存在的命令。

### 4.1 与正在进行的周线恢复隔离

日线设计和离线开发可先做，不要求所有周线来源异常先变绿。
日线真实写入与周线恢复、生产维护串行；检查是否有运行中的旧 attempt 和已冻结但待执行的包。

若已有合法冻结周线包，由其精确代码根完成该次操作；不得把本设计提交后的 develop HEAD
替换成旧包的执行版本。日线初次盘点可提前做只读预览，但实际日线 prepare 必须依据周线写入结束后的
新完整 D1 审计。后续任何共享数据变化都按原生 replan/hash 处理，不凭“只是日周共用数据”放过漂移。

文档提交不删除、迁移或重写旧 evidence，也不要求为日线重新完成已结算的周线单元。
现有代码要求 clean exact commit 时，文档提交同样可能使冻结身份失配；新旧执行根必须分清。

### 4.2 一次完整 D1 依赖盘点

固定 `as_of`、品种集合及其 hash、代码身份、配置身份、Canonical 根身份。
`as_of` 对应各 consumer 的 completed cutoff，不使用循环运行过程中的当前日期不断扩大范围。
按 `frequency=1d`、dependency-only 模式调用原生 readiness，保留完整原始报告及其 SHA。

主图窗口、统计窗口和各物理合约生命周期前缀由真实 reader/native planner 给出；
不能只补可见的 500 根、只补曾为主力的日期或仅检查 continuous/MAIN。
相同物理合约的多个 consumer 由原生 coalescing 合并到最大 required-through，保留全部 provenance。

`complete=false`、预算耗尽、UNKNOWN/UNSTARTED、枚举不全或共享元数据不能证明时不生成执行总包。
可以保留只读诊断；不得删掉错误行凑 complete，或用未审计的子集替代本次承诺的全集。
若资源确实不足，应先明确较小品种范围再重新盘点，不在执行中动态缩范围。

D1 已有数据来自何次 W1 操作不重要：严格读取可证明满足时自然不再出现修复目标。
过去成功的对象若仍在当前原生计划中，保留真实缺口并核查，不按旧名单过滤。
`REVIEW_REQUIRED`、SOURCE_EXCEPTION、完整性异常保持原分类，不与普通 PROPOSED 混写。

### 4.3 D1 总包与子包

复用现有每批最多 20 个完整单元的安全上限；由工具排序、分批和生成全部子包，不由用户手排。
日线单元为原生合并后的 `(symbol, physical_contract, 1d, required_through, plan_sha256)`。
每个单元的真正目标仍是 native planner 产生的 DatasetKey/月分区及精确 expected/missing 集合。

D1 包至少绑定原始审计 SHA、`as_of`、品种集合/hash、消费范围、代码/执行摘要、配置/Canonical 根身份、
profile/schema、子包相对路径/hash/顺序、原生 plan hashes，以及冻结 continuation policy。
hash 必须覆盖完整目标集合，不能只绑定首尾和数量；沿用 native 稳定序列化，不另算缺口集合。

总包只索引原生计划和执行证据，不成为 Catalog、market-data manifest 或第二完整性权威。
D1 包必须严格拒绝 W1、1m、60m、continuous、其他合约或 metadata target。
prepare、apply、零提交证明、最终 readback/replan 全链路使用同一个已验证 profile；
不能只改输入 parser，却在异常路径继续写死 `frequency=1w`。
D1 数据报告的 `frequency_scope` 是 `[1d]`，但现阶段 `release_stage` 仍可合法为 `weekly`；
两者分别校验，不能要求伪造 daily release stage。实际 stage 与代码/报告一并冻结。
新增任何实际参与执行或证据验证的代码路径都必须纳入 execution digest，不能用包 hash 掩盖未绑定 runner。

旧 W1 schema 的解析与行为保持原状，旧批准不因新增 D1 支持获得新范围。
不要静默升级旧文件、改写历史 hash、放宽旧校验，或把新 D1 manifest 交给旧 W1 importer。

### 4.4 一次正常执行

首次 provider 请求前校验总包及所有子包的完整性、输出根与单次 attempt 身份。
每单元执行前，按既有维护锁重新核对原生计划和配置/代码/数据身份；
漂移在 projection invalidation、来源访问和正式写入前阻断。

只调用 `HistoricalDataManager.contract_warmup` 的显式 D1 路径，复用 RQData adapter、
staging、hard validation、不可变 Parquet、Catalog 事务及 MDS strict-read。
不编写批处理自己的 Parquet writer，不直接改指针/row_count/coverage，不绕过 projection invalidation。

normalization 完全沿用 adapter 合同：合法零成交且正 close 的特定空/零 OHL 行可按现有规则规范化；
交易所全零零成交事实不能为了策略通过而改成正价。来源可持久化不等于牛哇可消费，
reader 的 SOURCE_EXCEPTION 必须继续显式表达。正成交零 OHL、部分零价等不放宽校验。

不得删除已有合法生命周期前缀或固定 through 之后已存在的合法同月 bar。
若涉及已有事实冲突、质量异常或实际需要纠错覆盖，退出普通缺数范围并单独审查。
D1 补数不顺带重建 W1/continuous；影响既有 W1 一致性的发现明确报告，不能宣称周线也已通过，
更不能扩大当前包的写入频率。共享完整性问题未清楚前阻塞受影响的进一步写入与完成结论。

每单元完成后保留来源 journal、原生结果、Catalog/Parquet/MDS 严格读回和零剩余目标 replan。
只有可靠读回的单元算 passed；没有发现目标的初始对象属于 audit 的 already-ready，
执行时计划意外消失是漂移，不伪装成 noop。

## 5. 异常与继续策略

| 情况 | 本次行为 | 完成判定 |
|---|---|---|
| 正常缺数 | 执行后严格读回；正常切换下一单元/批次 | 单元零剩余才 passed |
| 已保存的来源质量异常 | 只有精确代码白名单、全部已开始请求有匹配响应、零提交与未变 replan 均被证明，且本次总包批准该 policy，才隔离并继续独立单元 | isolated 仍未完成 |
| 网络、额度、锁冲突、identity/hash 漂移 | 停止本次 attempt，无重试、无等待循环绕锁 | 保留 failed/unattempted |
| 已部分提交后失败 | 停止，独立只读核对已提交分区；后续新审计生成剩余范围 | 整单元不计 passed，已提交分区单列 |
| COMMIT_OUTCOME_UNKNOWN、响应/journal 不全、清理或读回结果不明 | 停止；只读对账，不擅自回滚/删文件/接管 attempt | unknown，不当作未尝试 |
| 已存在 SOURCE_EXCEPTION/INTEGRITY_ERROR/REVIEW_REQUIRED | 留在原始依赖分母和异常清单，不进入普通 apply | 不能因无普通 target 宣称 data-ready |

复用旧来源证据仅指复核保存的来源事实，不复用旧写入批准或 W1 plan hash。
D1 引用旧响应前须证明同物理合约、当前 D1 request/expected dates 精确匹配、原始文件与 journal hash 完整，
并由当前 adapter 重放确认同一异常，再绑定新的 D1 原生计划。任一条件不满足只标待审，
不硬编码 B2411/RS 等合约跳过，也不静默发起新 source-only 查询。

现行 [维护合同](../../../openspec/specs/historical-data-maintenance/spec.md) 的
`Explicit ordinary recovery campaign source isolation` 及 DATA_CENTER 的来源隔离条款仅适用 W1。
实施 A 阶段必须同步两处 D1 例外及其精确条件；未完成合同与代码验证前，不能据本设计套用 W1 例外执行 D1。

W1 partial-exception receipt 不能直接充当 D1 zero-commit receipt；日线部分提交仍停批。
D1 的 parser/prepare 必须在环境打开、来源访问或子包生成前拒绝 W1 专用 partial-exception 输入，
包括从 prior campaign 间接携带的 partial exceptions；不能删字段或改 schema 将旧 receipt 转成 D1。
不为“继续执行”扩大现有来源错误白名单。其他错误即使看起来相似，也不能自动归为安全隔离。

## 6. 三层验收与结算

### 6.1 开始前：范围验收

新完整 D1 原生报告必须 complete、未耗尽预算、零 provider/生产写入。
输入报告、品种集合、生命周期与 completed cutoff 可核对；包中的每个目标均来自该报告及原生 planner。
完整报告可包含已明确分类的来源异常，complete 表示盘点完整，不表示所有数据正常。

### 6.2 执行中：受影响单元验收

每个单元执行上述来源/发布/严格读回/零目标检查；只检查实际依赖和受影响对象。
正常小批次之间不重跑整个 Web E2E 或全品种九组合 matrix。
若改动了共享 planner、Calendar/Session 或校验语义，则补跑真正受影响的验证，不能沿用旧证据。

### 6.3 结束后：独立数据验收

新进程在同一冻结 `as_of` 对全部已处理单元做原生 readonly replan，并对承诺品种范围重做完整 D1 audit。
既有 writer 若导致数据变化，按当前事实报告漂移/待验，不把固定时点报告伪装成全局数据快照。
若全部单元已成功，但最终进程超时、崩溃、审计不完整或结果保存失败，保留已验证的执行结算，
将最终输入验收标为未完成并返回非成功结果，不把成功单元改成未尝试，也不重下数据。
后续只读验收可独立重做并生成新观察记录；不得覆盖原始 attempt 终态或触发 apply。
执行结果未知与最终验收未知分别表达：后者不抹去已知提交事实，但阻止 data-ready。

自动生成一份可读摘要和机器结果，内容由原始 audit/journal/readback 派生：

- inventory_complete、ordinary_recovery_complete、各 consumer 的输入可用性分别表达。
- dependency 数、唯一合约单元数、分区数、missing endpoints 和实际 provider 请求数分开计量。
- 冻结执行单元满足 `N = passed + isolated + failed + unattempted + unknown`，互斥、不漏项。
- 部分提交的分区计数是 failed 单元的明细，不能再次加进 passed 单元数。
- 初始 already-ready 及审计中非普通异常保留在数据覆盖统计中，不因不在执行包而从总体分母消失。
- 以“品种×消费模块”列出可用、缺数、来源异常、证据不足及待审原因，禁止只给一个全绿比例。

没有普通剩余目标但仍有来源异常时，只能称普通恢复已结算，不能称日线全部可用。
未尝试、unknown、预算耗尽和元数据未证明均不允许被忽略。

## 7. 数据就绪与日线产品开放分开

本轮可在 `frequency=1d` dependency-only 审计中证明真实输入是否满足。
不得通过临时改 `OPEN_FREQUENCIES`、monkeypatch production gate 或公开 debug endpoint 来做验收。
未开放的日线在 public matrix 中保持 UNOPENED；它不否定已证明的数据事实，也不证明计算已通过。

三策略日线的真实 service/API/Web 计算验收与正式开放是后续独立产品任务，包含 capabilities、
旧链接/保存偏好/API 一致拒绝、各副图、参考交易及独立比较器，且仍不开放跨周期解释和 60m。
离线 fixture 可验证未来日线实现，但不得标为生产真实数据验收。
旧 trend-detail D1 兼容入口和 HTDY/SuBing/Free 保持原合同。

## 8. 最小工程边界与开发顺序

实施须先获设计批准；本次文档提交不启动下列代码工作。

| 顺序 | 工作 | 主要落点 | 出口 |
|---|---|---|---|
| A | D1 scope 与新包合同 | 现有 recovery/campaign 的 parser、schema/profile、prepare/apply/readback 路径；相关领域 OpenSpec | W1 旧行为不变；D1 全路径无跨频目标；离线测试与独立 Review |
| B | D1 自动结算与数据摘要 | 现有 readiness 原生结果及 recovery 证据的只读汇总；必要最小测试 | 一份报告回答范围、恢复、输入可用性；不创建新事实源 |
| C | 本地真实只读盘点与冻结 | 已批准代码根与持久共同证据根，命令进入 TESTING | 实测范围、包 hash、资源/自然维护冲突及剩余 Gate 明确 |
| D | 一次精确恢复及独立结算 | 原生显式 D1 manager | 获本次执行意图后运行；正常批次连续，异常按第 5 节处理 |

A/B 是一个日线工程主任务，可在同一任务分支连续完成，避免为每个小步骤新开会话。
从最新 develop 隔离任务，不改 main/runtime；必要测试与独立 Review 后按仓库流程集成 develop。
只在确认提交已进入 develop 后清理该任务分支/worktree；C/D 的持久 evidence 不存于待删工作树。
不同时重构周线故障恢复、添加后台自动化或实现 60m。

在实现中更新真实变化对应的 task contract/OpenSpec 和 TESTING；不为了文档对齐提前改 STATUS 为 Ready。
本次不新增可执行 Codex Prompt，不将设计提交解释成代码实施批准。

## 9. 实施验收用例

| 必须覆盖的场景 | 断言 |
|---|---|
| 显式 D1 与缺省七周期、W1 包混用 | D1 只含 contract/1d；所有跨 profile/schema/目标组合在 provider 前拒绝 |
| 错误路径仍写死 W1 | prepare、apply、零提交证明、最终 replan 均按同一个合法 D1 scope；测试 spy 捕获频率 |
| W1 已补齐部分 D1 | 新原生 audit 自动缩小实际缺口；既有数据身份/前缀/后续合法 bar 保留，无手工成功名单 |
| 主图齐备但参考生命周期不足 | reference 仍不可用，不用主图 500 根替代完整需要 |
| 同合约多个 owner/consumer | 原生 coalescing 不重复下载，provenance 无丢失 |
| 非交易日、上市/到期边界与 as_of | 沿用 Calendar/Session/lifecycle；未完成日和未来 bar 不进入输入 |
| 合法零成交与不合法零 OHL | 沿用原有精确 normalization；持久化允许但 consumer 不可用的事实保持分离 |
| 零提交已知来源异常和跨 profile 旧证据 | 仅完整证明且已批准 policy 可继续；不能直接复用 W1 receipt/plan hash |
| 第 n 个分区后失败、commit unknown、响应保存失败 | 前面成功不重写；未知不计 unattempted；不自动重试/续跑 |
| 同端点/数量但内部目标变化、代码/配置漂移、锁忙 | 原生 hash/identity 检查阻断，零未授权来源访问/发布 |
| 审计预算耗尽或 metadata/UNKNOWN 未解 | 不出可执行冻结包，不报告零缺口 |
| 写入全部成功但最终审计超时/崩溃/保存失败 | 单元事实保留，输入验收未完成，非成功退出；只读重验不触发下载或改写旧终态 |
| D1 携带旧 W1 partial-exception 选项或间接 prior binding | parser/prepare 在打开执行环境前拒绝，不将旧部分提交转换为零提交证明 |
| 完整结算仍存在来源异常 | ordinary complete 与 data-ready 不混用；各量纲和互斥计数正确 |
| D1 尚未开放且输入已齐备 | dependency 结论可成立，public matrix 仍 UNOPENED，所有 public gates 原样 |
| 既有周线与其他消费者回归 | W1 旧包语义、旧 D1 兼容入口及 HTDY/SuBing/Free 不变 |

实现验证从 [TESTING](../../../TESTING.md) 的 Newow/data foundation/工程检查中选择，先定向、后按影响扩展。
离线通过、代码 Review、真实数据结算、产品开放、Release 与 Runtime promotion 分别记录。

## 10. 完成条件与人工 Gate

本设计文档完成条件：事实依据可追溯，范围/取舍/异常/验收明确，设计自审与独立复核问题已修订，
提交内容仅为本目录文档。审查类型和实际验证限制见 [review](review.md)。

后续仍保留：设计实施批准、Lane 3 实现的必要独立 Review、真实来源/写入单次意图、
日线产品开放验收、main/tag 发布及 Runtime promotion。任何一项不能由本次文档提交替代。

本设计不保证来源异常可通过重下修复，不承诺未经测量的完成时间，也不以隔离代替真实数据恢复。
