# Newow 周线数据与异常统一恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 完成普通缺口与元数据的有界恢复，并对 PF2611 和九个 RS 给出独立可审的处置结果。

**Architecture:** 复用 metadata-repair、ContractWarmupPlanner/HistoricalDataManager、Catalog/MDS 与现有
readiness/summary。现场写入串行，规划和异常归因共享同一份原始证据，不增加新调度服务。

**Tech Stack:** Python、既有 guiyi CLI、PostgreSQL Catalog、Canonical Parquet、pytest。

**Spec:** [统一恢复设计](design.md)。可执行命令仅见仓库 `TESTING.md` 对应章节。

## 全局约束

- 设计审批不等于执行意图；metadata fetch/apply、provider 查询、Canonical apply 分别取得精确单次意图。
- operational 60、1w + 必要 1d companion、as_of `2026-09-13T06:36:13+00:00`；不改策略或收益合同。
- 元数据每批 targets 最多 64 条；owner 已取消旧 900 MB 预测门槛，不做 quota 探测、额度核算、流量估算或校准。
  原生请求清单/hash/计数仍校验身份与范围；真实 quota/权限失败停止，不自动重试。
- PF/RS 独立隔离；MainContractMap 不造事实；不动发布、Runtime、通知、Scope 和凭据。
- 本树只保存规划；执行从届时最新 develop 固定代码与导入身份，保留其他任务修改。

## R1 当前实施入口（唯一 active 清单）

本节取代下方早期 Task 1–5 的待办状态；早期设计审查、额度审批和失败记录仅为历史。
一个 `gpt-5.6-sol / high` 任务连续负责以下 R1–R6，不拆为多个并行数据执行任务。
当前设计基线 develop `74d7a71fcd061d25eb23d7d2142a075420125886`；允许范围内开发、测试、独立
Review 和条件满足后的 develop 集成，不设计或执行 main/tag/release/Runtime。

### R1：接收当前证据与固定执行身份

**Read:** 本设计、当前 AGENTS/STATUS/DEVELOPMENT/TESTING、对应 data/Newow canonical。
**Use:** 现有 acceptance/summary、metadata planner；不新增并行报告格式。

- [ ] 在新原生隔离 task worktree 核实 branch/HEAD/dirty/develop 依赖；默认从 project 创建后如不是 develop
  后继，先按仓库流程安全对齐最新 develop，不重置他人修改。保留 parent 与 primary evidence。
- [ ] 将本版设计及实施计划复制到任务自身同名文档并随任务集成；不要整体 cherry-pick parent 的旧分支。
- [ ] 校验持久原始报告 hash `787393d159b0bde955b7258e1251ad24730d45cd18b5a6dfc073db6f33879ff8`
  与原生 summary，记录其为写入前基线。896 普通候选、494 提案、联合 READY 6 均不得当当前计数。
- [ ] 校验 batch-03 apply/readback/post-plan：6,065 行、1,696 日期、63 目标已完成，当前缺键/请求 0；
  PT2608/PT2610 已完成 warm-up 也不重复。原生 plan/hash 与真实 Catalog 才是进度权威。
- [ ] 读取本节末尾父任务下载终态，再核 snapshot/hash/journal；不是从历史“待审批”段落决定重跑。
- [ ] 若需长时生产读取或获准操作，固定实际执行 commit 与 app/guiyi_quant 导入根；不能仅把 PYTHONPATH
  指向隔离树却允许 editable namespace 回落 mutable primary。不复制/显示 .env 或更改 Runtime。

### R2：完成剩余 metadata 的写入准备及获准后的闭环

**Use:** `services/quant-api/app/market_data/bounded_metadata.py` 的 `recheck_plan`、`fetch_metadata`、
`apply_metadata`；`app/market_data/session_clock.py` 的 `SessionWindowBatch` 共享 Session 解析。
**Tests:** `tests/data_foundation/test_bounded_metadata.py`、`test_newow_readiness_cli.py`，命令见 TESTING。

- [ ] 原剩余批次固定为 04/02/01；184 targets、7,012 日期缺键、Calendar 0。已下载完整快照只做离线校验，
  不重取；响应 journal 是 adapter 规范化响应，不宣称网络原文或 provider 计费次数。
- [ ] 逐批核 prepared、blockers 为空、plan/snapshot 语义 hash、完整来源一致性及输入不超过 16 MiB。
  超限不放宽 reader、不手改 snapshot；停在精确原因，设计有界重分批方案，重新批准需要的新请求。
- [ ] 提取每批真实 Calendar/Session 行数、日期键、旧事实保留范围、五表短事务锁影响，形成一份精确写入
  清单供 owner 在新任务中确认；不附额度预算审批。跨会话不能借用 batch-03 或 parent 的下载执行意图。
- [ ] 获对应一次 apply 意图后串行执行既有 insert-only writer；5 秒五表锁内 native recheck 必须相同。
  不改已有 Session/Calendar、不写 MainContractMap，不持远程请求跨 DB 写事务。
- [ ] 每次 commit 返回后新只读事务逐字段核对插入行、范围内既有行保留及共享 SessionWindowBatch 解析；
  同 targets 原生 replan 缺键/请求归零。commit unknown 只读核查后停，不自动重试或逆向删除。
- [ ] 前批变化使后批 hash 漂移则旧计划失效；先查明是否共享 Calendar 或自然维护变化，不能跳过 recheck。

### R3：重建真实剩余依赖，并独立处理映射缺证

**Use:** `app/market_data/newow/readiness.py`、`product_reader.py`、`historical_data_manager.py` 中
`ContractWarmupPlanner`、`_scope_diagnostic`；共享 Catalog/MDS mapping authority。
**Tests:** `tests/newow/test_readiness.py`、`test_product_reader.py`、`test_weekly_acceptance.py`。

- [ ] 元数据写后对原 60×3 W1 scope 做一次有界依赖重规划，包含曾 UNKNOWN 而未形成候选的依赖。
  先用已有依赖入口，不为了拿同一摘要反复跑完整 section matrix；最终全矩阵留 R6。
- [ ] 显式分开 metadata、mapping、普通缺口、SOURCE_EXCEPTION、INTEGRITY_ERROR 和仍未判定项。
  对旧 MAIN_CONTRACT_MAP_MISSING 查明是上游 Session 派生错误，还是确实缺某 symbol/date rank1。
- [ ] 真映射缺失只从权威 rule=2 来源形成精确日期方案，不从 D1/W1/主力后缀猜 rank1，不调用 broad
  synchronize/full update 顺带替换历史 Session。若现有入口无法精确安全写，先给最小接口设计、隔离测试与
  独立审查，再提交具体写入差异；不得先预设一定需要新 writer 或把 source/identity 歧义降级为普通缺口。
- [ ] 普通候选按原生归并的 contract/frequency/owner-through 去重，检查 W1 的全部 D1 companion。
  原始非正或完整性冲突的目标不提供普通 apply hash，不能因某 section 可读而解禁全 contract。

### R4：PF2611 与九个 RS 专项归因和最小工程修正

**Read:** `app/market_data/historical_data_manager.py`、`rqdata_adapter.py`、Catalog 指针与 shared reader；
`packages/quant-core/guiyi_quant/newow/product_adapters.py` 只用于确认消费者合同，不预先修改。
**Tests:** `tests/data_foundation/test_historical_data_manager.py`、`tests/newow/test_data_diagnostics.py`、
`test_readiness.py`；若确有 adapter/reader bug，再扩展对应现有 fixture。

- [ ] PF2611 锁定 W1 2025-11-21；RS2407/2409/2411/2507/2509/2511/2607/2608/2609 分别核查。
  从原报告提取 35 个异常分区标记，不重用 metadata 的老 RS2309/RS2311 代替专项对象。
- [ ] 对 Catalog 精确 URI 校验 hash/解析/生命周期/端点与同源 D1/W1；RS2507/2509 的 D1-only、
  RS2608 的 W1-only 标记均覆盖。每个合约独立归因，不从统一 reason 推断同根因。
- [ ] 必要 provider 核验先冻结具体接口/物理合约/日期/字段及 source 存储范围，取得当前单次意图后下载，
  不做额度计算；下载只提供来源证据，不自动授权 Canonical 覆盖。
- [ ] 只有复现本地 bug 才先写失败测试再修现有入口，测试覆盖真实坏事实与合法对照；检查前缀不变性、
  同源 D1/W1、缺失/重复/错身份和错误分类。未证明根因时不添加推测补丁或放宽正价政策。
- [ ] 真源非正价保留源事实与 Newow 阻断；本地损坏可修则列准确分区、旧指针、dry-run、恢复方法并另批
  apply。仅证明确为健康普通端点缺失的单项 RS 才进入 R5。不能安全修复时给出最小缺证并继续独立工作。

### R5：普通补数，先试点后串行闭环

**Use:** `ContractWarmupRequest`、`ContractWarmupPlanner.plan`、`HistoricalDataManager.contract_warmup`；
现有 CLI `contract-warmup` 的显式 1w scope，非默认七周期。
**Tests:** `tests/data_foundation/test_historical_data_manager.py` 及现有 warm-up/CLI 相关组。

- [ ] 以 R3 当前候选选一个依赖健康的小试点；原 EC2607 仅线索，旧失败/拒绝和旧 hash 不授权重跑。
- [ ] 先冻结每批单 contract、requested/effective through、D1/W1 分区与 hash；新任务汇总提交精确执行
  清单，不逐项追加额度审批，也不能凭旧 896 列表跳过 native preflight。没有受控写入意图则继续其他工程。
- [ ] 获匹配单次意图后按同品种闭环顺序串行执行；W1 和 companion 共享原生同批源快照，维护锁内重核，
  不额外单独下载同一日线、不扩通过日期、不取分钟数据、不碰 continuous/Map/Runtime。
- [ ] 每个成功批次独立 MDS strict-read、Catalog/hash/coverage 读回和 native replan 缺口归零；source缓存
  只限原生调用，不跨批把旧快照当最新事实。全队列首次 provider/validation/commit 异常停止写入链，保留
  已成功分区，明确未执行后续；不自动重试、续跑或换入口。

### R6：真实验收、文档同步与 develop 交付

**Use:** `guiyi data newow-readiness` 的 operational/1w/matrix 模式采集唯一完整报告；
`scripts/newow_weekly_acceptance.py summary` 从该报告离线生成摘要；该脚本 `pt` 模式仅做 PT 定向
Action/Reference 验证，不是全矩阵采集入口。完整执行参数见 TESTING；另用现有 Newow API 与
`apps/quant-web` 候选预览。
**Tests:** `tests/newow/test_product_contracts.py`、`test_product_adapters.py`、`test_reference_trades.py`、
`test_weekly_acceptance.py`；Web `tests/newowProductTypes.test.ts`、`newowProductChartPrimitives.test.ts`、
`newowDetailPresentation.test.ts`、`newowReferencePanel.test.ts`，以及对应现有 E2E。

- [ ] 在获准批次全部终止后，固定原 as_of 做一次完整 operational 60×3 W1 matrix；完整报告先持久保存，
  再由同文件派生 summary。scope/matrix coverage、UNKNOWN、WARMING、NOT_APPLICABLE、UNOPENED 全保留。
- [ ] 报告原候选→当前 remaining 的可追溯差异，区分未执行、失败、调查完成但数据阻断；6/180 旧数不沿用。
- [ ] 在隔离候选空闲端口真实只读验证 PT 初始 CLEAR、正常 BUILD/CLEAR 配对、来源阻断和 warm-up 展示；
  没有 BUILD 的 CLEAR 不制造参考收益/ReferenceTrade。保存 API 身份、浏览器/console 证据；fixture 与真实
  页面分别计数。依赖不足的 case 明确 BLOCKED，不为截图造价，不停止占用端口的其他服务。
- [ ] 如前端/接口需修，只修复现显示/合同消费缺陷，不开放 explanation、D1 或 60m、不修改策略决策。
  初始 CLEAR v2 已完成，不重写已获准语义；读取/消费外部内容保持现有严格身份校验。
- [ ] 运行直接相关测试，再按影响扩展模块/typecheck/build/E2E；命令只入 TESTING。完成 hygiene、canonical
  consistency、OpenSpec、secret scan 与 diff check。执行输出归属实际 commit，不拿旧测试声明新代码通过。
- [ ] 独立 Review 并修复全部 Critical/Important，复核后按授权提交/push/集成 develop；如无生产代码缺陷，
  可只交付实证与已审文档，不为“开发任务”强造改动。更新 STATUS 仅写本次已证明状态，保留其他车道内容。
- [ ] 交付 CODE/TEST/REVIEW 与 DATA/EXTERNAL_GATE 各自状态、实际批次与未完成原因；不生成 release plan，
  不 merge main、不打 tag、不切 Runtime、不发送通知。唯一下一步聚焦尚缺的最小精确 Gate。

### 父任务三批下载交接（COMPLETED）

父任务按本轮新意图依次各尝试一次 batch-04、02、01，23,537/23,537 个元数据请求响应完成；无显式 quota
查询，无 DB/Canonical 写入，无重试。冻结源为 `5b31cf7c1ceb5350d4a5ea0a3d9328635d0ea62d`，相关 metadata/历史维护/
Newow 实现与本次 develop 一致。持久输出目录为主仓库
`outputs/newow-weekly-data-recovery-20260913/metadata-plans-247/`；源响应、snapshot、invocation/result/
execution 沿用 batch-03 的既有格式，独占新文件，不覆盖旧证据。

| 批次 | 完成时间 CST | targets / 日期 | 响应 | Session 行 | snapshot bytes |
|---|---|---|---|---|---|
| 04 | 23:34:37 | 56 / 4007 | 6036 | 15253 | 7042575 |
| 02 | 23:37:12 | 64 / 1458 | 7366 | 5798 | 4451465 |
| 01 | 23:40:49 | 64 / 1547 | 10135 | 6108 | 5692605 |

每批均 prepared、blockers=[]、Calendar 0、exit 0，来源与配置元数据检查不变，均低于 16 MiB 输入限制。
snapshot 语义 hash：04 `a6fee971e5b3031166f8ef53f40068b56319afb7812edced62de2a45ff68e206`；
02 `8975ad46347a36da40179d5792724d6c494f6880d56dda15cc513a32a2357464`；
01 `178c4868a9c3a6faac7d4646a907134ab22fad6953162db9d1cc3c66f50a6b67`。
与各自原生 plan、fetch result/execution、全部 23,537 条 journal 逐项独立离线对照通过，三个批次的
7,012 个 Session 日期键互不重叠。合计 27,159 行只存在于源快照，尚未提交数据库。
本次下载意图已消费：新任务不重新下载，不把 prepared 视为写入许可；按 R2 使用现有快照准备精确 apply。

### 本版设计与实施计划验证

已按当前代码核对入口、合同版本与测试路径。独立 Review 首轮发现 R6 误将 summary/PT 脚本当作
全矩阵采集入口；已改为 readiness CLI 采集、summary 离线汇总、pt 定向验证，独立复审确认关闭。
最终 `REVIEW_COMPLETE — NO_BLOCKING_FINDINGS`，允许交付单个 Sol high 实施。
本轮实际验证：固定源码相关六组 pytest 386 passed；文档 hygiene/canonical consistency 22 passed，
OpenSpec 9 passed，secret scan 0 findings，新增文档 whitespace 检查通过。固定源码相关模块与
`74d7a71fcd061d25eb23d7d2142a075420125886` 比较无差异；这些是工程验证，不是新的全矩阵数据验收。

## 以下为历史计划与逐次执行记录（非当前待办）

旧额度约束、审批下一步和未勾选 Task 状态仅描述当时；当前执行只遵循上方 R1–R6、最新设计与真实 receipt。

## Task 1：恢复可执行的证据基础

**Read:** `STATUS.md`、`docs/DEVELOPMENT.md`、`docs/DATA_CENTER.md`、
`openspec/specs/historical-data-maintenance/spec.md`、`outputs/newow-weekly-60-20260913/readiness-summary.json`。
**Use:** `scripts/newow_weekly_acceptance.py`、`services/quant-api/app/market_data/newow/readiness.py`。
**Produces:** hash 验证的完整原始报告，及由同一文件导出的 summary；不是新建缺口数据库。

- [ ] 核对最新 develop、任务冲突、现场代码、自然维护窗口和维护锁；不停止或抢占自然任务。
- [ ] 从旧 summary 的明确引用找回完整报告并核 hash、scope、as_of、schema；未找到就保留证据不足结论。
- [ ] 如需重采集，先取得当前任务有界生产只读连接意图；一次 60×3 W1 审计，max-work 100000、timeout
  1800 秒。只输出证据，provider_requests=0、writes=0；预算耗尽/失败/锁忙停止，不循环跑。
- [ ] 证据保存位置应独立于可清理 worktree；仓库外新写入目录先列精确路径并获批准。保留原始 incomplete
  结果，不为了凑完整修改它；summary 必须识别异常/UNKNOWN，拒绝 foreign scope。
- [ ] 用原始明细重新列元数据关联、普通候选、PF/RS 和其他阻断；494/247/896 仅作为旧摘要对照。

## Task 2：元数据精确补齐

**Use:** `services/quant-api/app/market_data/bounded_metadata.py` 的 `validate_targets`、`plan_metadata`、
`fetch_metadata`、`apply_metadata`；执行入口为 `TESTING.md` 的“有界 metadata”章节。
**Inputs:** Task 1 明确 symbol/contract/through；**Produces:** 既有 plan/snapshot/apply 输出和精确键的读回。

- [ ] 以最多 64 targets 分批；检查 resolved_targets 的生命周期和每个 owner-through，不用品种模板猜日期。
- [ ] 输出 Calendar/Session 缺失业务键、已有日期、请求明细、plan hash、影响与恢复说明，提交单批 fetch 意图。
- [ ] 未知交易日先 classification；新增 Session 或供证请求必须新 plan/新 fetch 意图，不串行自动追加。
- [ ] 检查响应范围、来源一致性、重复/缺失、夜盘证据及完整 Session 日期；blocked snapshot 不进入 apply。
- [ ] 用 plan hash + snapshot hash 提交单批 DB apply 意图；执行前锁内重核，成功后只读 replan 和 MDS 依赖读回。
- [ ] 前批影响后批共享日期时重规划；已有但疑似不完整的日期、真实映射缺失移交专项，不计“已修复”。

## Task 3：PF/RS 根因闭环

**Read:** `services/quant-api/app/market_data/historical_data_manager.py` 的 `_scope_diagnostic`、
`_classify_contract_partition`，及 `services/quant-api/app/market_data/newow/readiness.py` 的 scope_conflicts。
**Inputs:** Task 1 完整 diagnostics 及 Task 2 元数据读回；**Produces:** 每个异常独立的证据、分类和处置结论。

- [ ] 分别检查 PF2611 与九个 RS 的精确 Catalog 对象及 companion；逐条记录原因，不从粗分类推断来源错误。
- [ ] 对照设计表区分源异常、本地损坏/算法缺陷、端点缺口与证据不足；元数据更正后重核生命周期/端点结论。
- [ ] 需 provider 核验的异常只形成精确请求候选并申请一次 fetch；不同时请求正式覆盖。
- [ ] 若复现代码缺陷，先补具体失败 fixture，修正最小代码并更新受影响 canonical/版本，再独立 Review；
  缺陷尚未复现前不预先指定补丁，不借此改全局 SOURCE_NONPOSITIVE_PRICE 策略。
- [ ] 确认可修的分区生成独立重建方案，明确原指针/影响/恢复及批准 Gate；不能安全修复的保留明确阻断。
- [ ] 只有新 diagnostics 证明纯缺口的单个 RS 可重新进入 Task 4，不整体解除九个目标的 REVIEW_REQUIRED。

## Task 4：普通补数及逐批验收

**Use:** `services/quant-api/app/market_data/historical_data_manager.py` 的 `ContractWarmupRequest`、
`ContractWarmupPlanner.plan`、`HistoricalDataManager.contract_warmup`；`TESTING.md` 的 W1 recovery 用法。
**Inputs:** 元数据更新后的新 plan，含此前因元数据阻断而未能规划的目标；**Produces:** 逐批现有输出及零缺口读回。

- [ ] 重建普通队列，复核完整 W1+D1 scope diagnostics；去重 companion 重叠，保留原 owner-through 关联。
- [ ] 先做一个依赖齐全的小试点。EC2607 仅为候选，重新 dry-run，plan 模式不传 apply-only expected hash。
- [ ] 单一合约批次列精确窗口/分区/hash/请求/预算证据与恢复方法，取得当前单次 Canonical apply 意图后执行。
- [ ] 每次先核共享当日用量、维护锁和计划漂移；如果不能证明预算安全，不执行该批。失败不自动重试。
- [ ] 读回 MDS、Catalog/hash、已批准缺口 replan 为零及真实 quota 差值；成功分区保留，部分失败准确记录。
- [ ] 同品种可独立闭环的后续目标优先，但每批仍重新规划；PT 已完成批次不重跑。安全独立只读工作不因
  某个异常阻断而停止，但任何未获批准的写入不得继续。

## Task 5：最终统一验收与交付

**Use:** `scripts/newow_weekly_acceptance.py`；**Tests:**
`services/quant-api/tests/data_foundation/test_bounded_metadata.py`、
`services/quant-api/tests/data_foundation/test_historical_data_manager.py`、
`services/quant-api/tests/newow/test_readiness.py`、
`services/quant-api/tests/newow/test_weekly_acceptance.py`、
`services/quant-api/tests/data_foundation/test_newow_readiness_cli.py`。

- [ ] 如有代码修正，按修改范围运行上述 fixture 及 TESTING 中 metadata/provider/CLI 回归，保留实际输出，
  独立 Review 后再进入相应生产 Gate；无代码修正不以新代码任务扩张范围。
- [ ] 所有获准批次终止后，在固定截点做一次完整 60×3 W1 审计；原始结果持久保存后离线 summary，不重复查询取摘要。
- [ ] 对比普通剩余、元数据剩余、PF/RS 结论及新发现异常；未知、预算耗尽、未执行目标准确保留，不宣称全 READY。
- [ ] 报告实际完成/失败/未执行批次、真实资源消耗、Review 与外部 Gate；如存在真实源异常，单独表述“调查完成、
  数据仍阻断”。不将完成调查或合入 develop 表述成数据完整或 Runtime Ready。

## 本次规划验证

文档新增，不修改生产代码、STATUS 或 canonical；验证使用 `TESTING.md` 的 repository hygiene、
canonical consistency、OpenSpec、secret scan 和 diff check。独立审查重点为明细可恢复性、元数据分批限制、
重复目标/hash 漂移、异常隔离、预算证明和单次执行意图。规划获审不替代以上未勾选现场步骤。

2026-09-13 实际离线验证：本规划树 repository hygiene + canonical consistency 22 passed，OpenSpec
9 passed，secret scan 0 findings；新文件 diff whitespace 检查无问题。最新 develop `ef2e087d1` 的
`test_bounded_metadata.py` + `test_readiness.py` 134 passed。上述 fixture 不是现场数据恢复证据；
本次没有真实 provider 请求、生产 DB/Canonical 写入或 Runtime 操作。

独立只读审查结论：`REVIEW_COMPLETE — NO_BLOCKING_FINDINGS`。已确认 64 targets 上限、原生 through
归并、异常隔离、分区原子性和独立 Gate；每日字节预算不是现有工具的硬限额，仍需真实消费证据与缩批停止。
`preopen-reliability` 的未提交修改属于其他任务，执行前继续协调，不能覆盖或清理。
设计可进入证据恢复与规划阶段；完整原始报告、逐批精确执行批准及最终数据验收仍未完成。

## 2026-09-13 单次只读审计中断

owner 批准上述首步一次 60×3 W1 只读审计及主仓库
`outputs/newow-weekly-data-recovery-20260913/` 报告保存；该意图不包括补数、DB/Canonical 写入。
22:04:07 CST 启动，维护锁预检为空，固定起始 commit 为 `ef2e087d1`。运行期间其他任务集成后主树
HEAD 变为 `5b31cf7c1ceb5350d4a5ea0a3d9328635d0ea62d`，包括 `market_read_service.py` 等代码变动。
因固定执行基线漂移，核验本任务父子 PID 后对审计子进程发送 SIGTERM，22:07:48 CST 已退出，未重试。

`invocation.json` 与 `execution.json` 已保存；`full-readiness.json` 为零字节，不是有效报告，不能生成
正式 summary、刷新 896/494 或认定缺口变化。execution 的 `signal=SIGTERM`、
`code_commit_unchanged=false` 为中断事实；其中 `stopped=false` 是包装器自身预算停止标志未触发，
不能解读为进程未被 operator 终止。本轮没有执行任何补数/apply；没有取得可核验的 audit 终态计数。

根因是从会被并行集成推进的主 develop 工作区导入源码，仅核对起始 HEAD 不足以冻结长时间执行。
后续审计须先以明确 commit 构建固定、隔离的源码副本，核对实际导入文件与 scope/config 身份；
正式 Runtime 不切换，其他任务不停止。保留本次目录，不覆盖零字节文件或改写 receipt。
任何再次生产只读采集均需新的单次执行意图，并使用新的独占 evidence 子目录。

## 2026-09-13 固定副本重采集准备

owner 新批准固定 `5b31cf7c1ceb5350d4a5ea0a3d9328635d0ea62d` 隔离副本、原范围的一次只读审计。
已从 Git 导出独立源码快照，385 个源文件逐一匹配 Git blob，快照设置只读；不改变任何 worktree 的 HEAD。
快照身份摘要为 `cb0eb0aacf38442a54c43496e251301586cd1c62daf65110201fd2461eb8e1fe`。
沿用现有 Python 依赖，但在导入任何 app 子模块前将 namespace 搜索路径限定到快照；所有 app/guiyi_quant
模块来源检查通过，不容许 editable 安装回落主 develop。离线准备没有连接生产数据库。
现有配置由进程正常加载，不复制/输出凭据；Canonical 指向与原主仓库配置相同的现有根，不回落快照下的空数据目录。

固定副本 `test_weekly_acceptance.py`、`test_readiness.py`、`test_newow_readiness_cli.py` 共 93 passed；
包装器语法及离线导入检查通过。现场采集于 22:15:46 CST 启动，使用新的
`outputs/newow-weekly-data-recovery-20260913/isolated-5b31cf7c/`，保留上一尝试目录与记录。
运行终态、报告 hash、完整性及清单数量以本次完成后的原始 JSON 和派生 summary 为准。

### 重采集终态与离线清单

22:32:16 CST 已结束，耗时约 990 秒，无信号终止、未触及预算；原生 `work_used=4965`、
`budget_exhausted=false`、180 case 全部枚举且无 UNSTARTED section。原生 `status=incomplete`、
`complete=false`，因此 CLI exit 1；这是存在 UNKNOWN 未决项的业务结果，不是本次采集崩溃。
固定源码内容、实际模块来源、配置元数据检查均通过，provider_requests=0、writes=0。

完整报告 21,468,106 bytes，SHA-256 为
`787393d159b0bde955b7258e1251ad24730d45cd18b5a6dfc073db6f33879ff8`，与旧摘要记载的原始报告 hash 完全一致。
原生离线 summary 验证 exit 0、`valid=true`、violations 为空；scope_covered 和 matrix_covered 均 true，
audit_complete 仍 false，UNKNOWN 未决计数 2233，chart READY 6、reference READY 9、联合 READY 6。

新持久证据均位于主仓库 `outputs/newow-weekly-data-recovery-20260913/isolated-5b31cf7c/`：

- `invocation.json`、`execution.json`：固定身份、执行参数及终态。
- `full-readiness.json`：唯一完整原始报告，不修改。
- `summary.json`：从该原始文件经既有校验器生成，没有第二次生产查询。
- `recovery-index.json`：原始行号关联、元数据目标及普通/专项候选的离线清单；不是 metadata plan 或写入许可。

真实清单仍为 896 个普通候选（203872 bars、17529 个规划请求，不是已执行用量）；
494 行元数据提案可提取为 247 个明确 symbol/contract/through 目标，覆盖 47 品种，无无法提取的提案。
按单批最多 64 targets 至少需要四批元数据规划；实际缺失 Session 日期、行数和 provider 请求仍须由
metadata planner 核定，不能用 247 代替。RS2311 的两个不同 through 保留，不手工扩窗去重。

PF2611 仍为 2025-11-21 W1 非正价格、historical_candidate_recoverable=false。
九个 RS 的 scope diagnostics 均包含 SOURCE_NONPOSITIVE_PRICE，共 35 个合约/频率/月分区标记，
且各自伴随 REPLAY_ENDPOINTS_MISSING；这是已有读取数据的诊断，不等于已证明 RQData 原始源有误。
其中 RS2507、RS2509 只在 D1 companion 发现非正标记，RS2608 只在 W1 发现，不能只看单一频率或合并根因。
九个目标均继续 REVIEW_REQUIRED，未转入普通队列。精确分区与消费者关联保留在原始报告和离线清单中。

本次批准的只读重采集与清单提取已完成；整体恢复任务仍 PARTIAL。唯一下一步为根据已恢复的 247 目标，
生成有界元数据缺键规划，再分别提交精确 fetch/apply Gate；没有执行真实补数、metadata fetch/apply、
PF/RS provider 核验、发布或 Runtime 操作。

## 2026-09-13 元数据缺键计划已生成

owner 本轮要求已完成到“生成并提交批次”阶段，详见 [精确元数据批次](metadata-batches.md)。
原生四批 targets 为 64/64/63/56，总计 247；同一只读 Catalog 快照得到 8,708 个唯一 Session
日期缺键、Calendar 缺键 0、29,325 次规划元数据请求。目标并集与输入清单完全匹配，跨批没有重复
Session 业务键或请求。四份原生 plan 及输入、执行记录已保存在主仓库 metadata-plans-247 evidence 目录。

本次只读规划 exit 0，实际 provider 请求和生产写入为 0；真实 snapshot、Session 行数和写入批准
仍未产生。首批候选为 batch-03，须预算核实和精确单次 fetch 意图，随后按真实响应独立提交 apply。
计划通过不等于下载或写入批准；不可按旧的笼统批准自动执行四批。

本轮固定副本元数据/CLI 回归 168 passed；规划树 hygiene/canonical consistency 22 passed，OpenSpec
9 passed，secret scan 0 findings；四份落盘计划再经原生 validator 离线校验通过。所有验证均不证明
现场缺键已恢复，896 普通候选及 PF/RS 专项仍未执行。

本批次独立只读 Review 已完成，无阻断发现，允许提交四份计划及审批边界；fetch/apply 仍为
EXTERNAL_GATE_PENDING。大批 snapshot 超过 CLI 16 MiB 输入限额的风险仍须在下载审批时处理。

后续 owner 单次批准直接下载 batch-03，23:07:35 CST 已完成 5,788/5,788 请求响应，账户用量增量
4,065,221 bytes，未超额。原生 snapshot prepared、blockers=[]、3,694,308 bytes，包含 6,065 行
Session/1,696 日期、Calendar 0；原生离线校验及 journal 对照通过。生产写入和重试均为 0。
精确 plan/snapshot hash 与 apply 终态见[本任务执行就绪记录](execution-readiness-20260913.md)及持久
evidence 根的 `metadata-plans-247/batch-03-*` 原始 JSON。
Task 2 仅完成此批 fetch；apply、其他三批和整体数据恢复验收仍待相应独立意图，不标记全部完成。

再后续 owner 明确批准 6,065 行 Session 的一次 apply，23:14:47 CST 成功完成：新增 Session 6,065、
Calendar 0，apply_calls=1、retries=0；新只读事务逐行核对和 1,696 日期共享 Session 解析通过。
原 63 目标写后原生 plan 的 Calendar/Session 缺键、provider requests 均为 0。
Task 2 的 batch-03 元数据闭环已完成；其他三批、Task 3/4 及整体 W1/MDS 验收仍未完成。
