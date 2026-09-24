# Unified Reference Trading P6/P7 Design and Implementation Plan

> 执行者使用 superpowers:executing-plans；按依赖连续完成实现、定向测试、独立 Review 和条件满足的 develop 集成。生产操作保持独立 Gate。

**Goal:** 在已经落地的 P0–P5 上增加盘中参考交易维护、持久观察恢复、forward 查询和 HTDY first-seen 候选模型。

**Architecture:** 复用现有 reducer、AdapterCheckpoint、PreparedBatch、六表仓储与快照查询；增加受控 activation、validated Live 输入、独立 reference worker 和 forward reader。不从 AlertEvent 推导交易，不触发通知。

**Tech Stack:** 现有 Python/Decimal、SQLAlchemy/PostgreSQL、FastAPI、Vue；现有 Redis 只作 Live 输入与唤醒来源。

**Spec:** `openspec/specs/reference-trading/spec.md`；总体设计 `docs/superpowers/specs/2026-09-19-unified-reference-trading-design.md`。本文件细化 P6/P7，不重开已完成 P0–P5。

## 1. 调查基线与授权

2026-09-23 develop `97fec2e3ff3b503bd4b3d80f8fc0b08eb077e18d`。
当前主树另有 CJ/OI 周线计划与 outputs 未提交文件，不属于本任务，禁止暂存/覆盖/清理。
STATUS 显示 P5 已发布、现役 v1.10.25；生产 schema 0047、RB 十条 historical 流 READY 且 disabled。
生产 reader 仍 legacy，其他品种构建和全局 reader 切换未完成。这些不是本次 P6/P7 编码的前置阻塞，也不授权本次代做。

用户本轮授权设计并新建 GPT-6 Sol / medium 任务开发。允许隔离开发、隔离测试、Review、普通 commit/push、满足条件后集成 develop。
不执行生产 migration、bootstrap/advance、Scope、reader 切换、Redis 写入、服务安装/启动、provider 下载、通知或 main/tag/release。
开发可实现受控操作工具；工具存在和 dry-run 通过不是现场执行权限。
实施前重新核对 develop，保留其他任务修改；不得把生产批次历史授权用于新的操作。

## 2. 当前实际可复用接口和缺口

| 已存在 | P6/P7 用法 |
|---|---|
| `reference_trading/contracts.py` 的 `PreparedBatch`、`SourceAction`、`CheckpointToken`、`DependencyAdvance` | 沿用 forward observed_at、严格状态及依赖证明；不能造第二套提交 DTO |
| `reference_trading/repository.py` 的 `seal_seed/load_checkpoint/commit_batch/read_batch/record_diagnostic` | 复用行锁、幂等、快照、seed 与诊断；新增 activation/capture 必须遵守既有锁顺序 |
| `guiyi_quant/reference_trading/adapters.py` 与 `strategy_checkpoint.py` | 复用完整状态序列化、输入 fingerprint 与策略状态；保持原历史 golden |
| `reference_trading/service.py` 的 historical 编排 | 继续负责固定计划的 historical 操作；不把实时数据塞进其 Canonical source token |
| `HistoricalReferenceQuery` / `api/reference_trading.py` | 当前拒绝 forward；扩展共享查询与独立 forward readiness，不去掉模式校验了事 |
| `presentation_v1` | 实时提交同样保存展示事实；GET 不执行 Kernel，不从动作猜缺少的指标/信号 |
| `MarketReadService` | 复用 typed completed Live 读取、真实合约、交易日和窗口校验，不复制 resolver |
| `HtdyOriginalEvaluator.evaluate_first_seen` | 当前精确 32 Bar 窗口，仅最后一根；纯评价抽取后双方复用，不调用 transport |

关键缺口：仓储没有启用入口；stream 尚无完整 activation 身份；缺 pending observation capture；缺 worker；
P5 公共 GET 只支持 historical；缺 HTDY adapter/checkpoint/model；缺运行健康与默认关闭的部署组合。

## 3. 范围与能力矩阵

| 能力 | 首版开发范围 | 不推导的权限 |
|---|---|---|
| SuBing forward | 15m/30m/60m adapter、completed 输入、查询与隔离运行；D1 仅在权威完成输入具备时按源可用时刻记录 | 不扩大苏冰 15m Alert Scope |
| Newow forward | 三策略复用现有适配；60m 独立测试；D1/W1 为权威完成源到达后的观察，不造盘中日/周 Bar | 不自动开放尚未通过产品 Gate 的组合 |
| HTDY forward | 支持已存在且验证通过的观察周期；32 Bar first_seen + 独立参考模型 | 不复制现有 Alert Scope 为 Reference Scope |
| historical 后续更新 | 编写 Canonical 更新后的只读 advance plan 与对账编排；执行只接受明确维护授权范围 | 不自动重建、补数或开启全品种后台写入 |
| forward API/Web | 共用分页/统计/交易表，显式模式、启用起点与观察截止 | 不切生产全局 persisted reader |

所有策略/周期须列出 code / fixture / source readiness / product capability / enabled 五列；缺权威输入明确 unavailable。
D1/W1 的 observed_at 是实际读取并捕获该权威完成输入的时间，不回填成交易日收盘时间；未结束周期不评价。

## 4. 启用与禁用的合同

新增 `activation.py`，暴露 plan/dry-run 和明确 apply 入口；注册能力与生产启用分离。
ActivationPlan 绑定 host/environment、exact code/schema、stream identities、model/observation policy、输入边界、
预热 hash、recording_start、预算、恢复政策、expiry、plan_hash。计划过期或预热/owner 已变必须重规划。
持久保存实际激活 receipt。recording_start 不得早于实际激活，不得以旧 plan 的时间伪造已观察区间。
默认所有流 disabled；worker 只读明确激活的 forward 流，不从历史 READY 推导 enabled。

在一次受控事务中：核验身份/版本/seed 完整性 -> 发布独立 forward seed -> 设置 enabled/activation receipt/row_version。
指标可以历史预热，但 reference state 必须 FLAT。不能从 historical checkpoint 直接携入 OPEN 或旧 watermark。
启动时 HOLD 后的首个 CLEAR 保存 `NO_OBSERVED_ENTRY`，不伪造牛哇生命周期初始 CLEAR。
禁用必须增加 activation generation/row_version；计算中的旧 worker 在提交前检查 generation 和 enabled，禁用后不能再提交。
重复同一 activation plan 同一内容为 no-op；改变范围、模型或重复激活已结束的记录段不能覆盖旧 receipt。
重新启用先检查停用区间完整性；缺失按 observation gap 处理，不直接接上旧 OPEN。

新增 schema 仅为 activation/receipt/索引所需，优先复用 batch evidence；现有 0047 已生产应用，禁止改写旧 migration。
新 Alembic revision 以实施时实际唯一 head 为父节点；schema 变更只在专用可销毁测试库执行。

## 5. 持久捕获与原子投影

流程：唤醒 -> 按 stream 获取已完成有效输入 -> 耐久捕获输入 -> 纯评价/投影 -> 现有 PreparedBatch 原子提交。
不能只在提交交易后才保存来源，否则崩溃后的 first_seen 无法恢复。

推荐复用 `reference_batches` 增加独立 capture kind（按实际 CHECK 约束新增 migration）：
- capture_id/hash 唯一；包含 stream/activation generation、前序有效水位、source kind、完整输入窗口/Bar、
  source fingerprint、owner/session/quality proof、first observed_at、input eligibility、strategy schema。
- capture 不增加有效 seq，不替换 checkpoint，不对交易列表产生记录；完整性/大小检查失败不保存半份证据。
- pending capture 先被单流串行处理；PreparedBatch.source_evidence 关联 capture_id/hash；提交事务同时记投影已消费关联。
- capture 一旦保存，retry/resume 不能修改 observed_at/输入；相同身份不同内容为 conflict。
- input payload 有字节/Bar 上限；HTDY存准确32 Bar；其他策略存精确增量输入和可复现 seed/checkpoint，不保存无界全历史副本。
- capture / commit 与 disable 都遵守 stream->revision 锁顺序；禁用后未投影 capture 保留且不继续推进。

commit 返回不明先按 batch identity 只读核对。确认已提交返回原 receipt；仍不明确则停该流，不自动重试。
真正未提交的重试必须属于配置的恢复政策；首版默认不做不明结果自动重试。各流失败隔离。
已有仓储幂等键是 `(stream, revision, batch_key)`，不能按旧设计文案误改为跨 revision 全局唯一。

## 6. 输入与调度

`forward_inputs.py` 组合现有 MarketReadService、MDS/Session/owner validator，输出严格 `ForwardInputEnvelope`。
envelope 至少含 activation generation、strategy input、bar_end、trading_day、observed_at、contract、owner/calculation segment、
expected endpoints、source kind、source fingerprint、eligibility。Kernel 不读墙钟，now 只由编排注入。
typed Live 判定的非实时/恢复来源不能自动取得 HTDY first_seen 资格；明确保持既有 eligibility 规则。

分钟桶依据 Session；必须证明当前桶和与持久水位之间的输入连续性。午休、夜盘跨日、短尾桶、节假日不是缺口。
上一根正式 Bar 结束后，新主力预热可以读取更早物理 Bar，但不生成 owner 外动作、不倒退正式水位。
32 Bar 仅是 HTDY 当前评价合同，不能用它替代苏冰/牛哇的完整指标状态或预热合同。

首版一个独立 reference worker，计算并发1；队列只存有界去重 stream 唤醒键，不存不可恢复的唯一行情事实。
开发初始预算：最大512个待处理键、每次轮转最多32个捕获单位、单流每轮5秒协作预算、5秒扫描已启用流水位。
每个 pending capture 的字节上限复用现有证据/seed限额；实测过大应明确报预算不足，不能截断输入。
这些是开发默认，不是生产容量承诺；基准测试后形成 activation 中的精确资源预算。
公平轮转；无信号 Bar 同样保存状态/mark/水位。超预算保留未处理位置，不能忙循环或无限积压。
Pub/Sub 丢失时从 source watermark 发现差距；若历史 Bar 已错过 first_seen 时机，不利用扫描伪造旧观察。

## 7. 缺口、换月与盘后核对

- 同 capture 的重复输入 no-op；旧 owner迟到不能更新新 owner；相同身份不同输入阻塞。
- 有完整 durable capture 的停机可以按原时间重放观察；未捕获区间不是已观察事实。
- 缺观察默认 BLOCKED，不把旧 OPEN 穿越未知区间；按明确恢复政策生成 OBSERVATION_INTERRUPTED，无 exit/return，
  记录新 observation segment 起点、重置 reference FLAT、预热后继续。该政策不会补发通知。
- authoritative rollover -> ROLLOVER_INTERRUPTED；proven price unavailable -> DATA_INTERRUPTED；未知缺口不能冒充已证明价格中断。
- 盘后 Canonical 更新只唤醒/对账，不把全策略计算塞进数据维护锁；维护忙则延期，不能绕过读写互斥。
- 对账记录 capture 与正式输入的 matched/mismatch/pending。差异不改原 observed action/时间，historical另按P4重建计划处理。
- 本阶段可实现已批准范围内的 append-only historical维护编排；REBUILD_REQUIRED、范围扩大和源修订停在计划，不自动修复。
- 当前 production historical streams 保持 disabled；不得为了盘后运行绕过 P4 现有 disabled/candidate 条件。

## 8. P7 HTDY候选模型

实现提案 `htdy_first_seen_reverse_close_v1`，只作为独立候选注册；canonical明确模型代码完成与owner模型接受是不同状态。
用户已要求P7开发，不重复申请编码许可；现有 `MODEL_NOT_APPROVED` 不能在无明确业务接受事实时被写成正式已批准。
可在隔离测试中显式接受候选；生产 activation 仍要求模型接受和精确启用批准。

- 复用原 Kernel 和 CURRENT_BAR_CONTEXT_BARS=32、latest-only first_seen；必要时抽取纯评价函数，Alert与Reference双方使用。
- 首个 buy 开多，sell 开空；同向不加仓；反向 CLOSE 显式关联旧 entry，再 OPEN，sequence稳定。
- 信号Bar Close 为乐观参考价，Decimal零费零滑点；保留真实observed_at，不称成交。
- buy/sell同Bar冲突捕获证据、阻塞有效推进；不能自行选先后。
- 历史窗口因后续输入重绘不修改已存动作；恢复基于实际捕获序列，不能用最终历史曲线重算观察事实。
- 不导入旧AlertEvent作为参考历史，不建设HTDY retrospective收益，不修改Kernel公式/窗口/通知规则。
- checkpoint保存精确窗口、policy/model/schema和参考状态；不能仅存最后方向。
- 同向观察仍存presentation，不能因没有新交易而让页面信号消失。

## 9. 查询、Web与健康

扩展已有统一查询模块，保留HistoricalReferenceQuery薄兼容入口；底层仓储/分页/token/Decimal统计复用，不复制第二套API。
模式必须来自持久stream身份；forward不调用historical-only统计适配强行拼装。
snapshot需绑定 activation generation/recording_start、revision/seq、窗口/cutoff、模式/统计政策与源证据。
forward查询同时约束event bar和observed_at；marks/无动作中断也须过滤实际观察时刻。跨模式cursor明确拒绝。
已保存presentation是唯一展示来源，GET不得触发evaluate/replay/build/写入。

Web增加“历史参考 / 盘中观察参考”显式入口，未启用显示未启用，不显示虚假空交易。
显示recording_start、computed_through、观察连续性和Canonical核对状态；默认保留原历史页面入口与reader配置。
HTDY接入公共ReferenceTradePanel；其图表回看信号与首次观察记录标识不同，不拿重绘图形证明过去有交易。
新页面/API构成P6/P7交付，不能只完成worker后要求下一任务补读写闭环。

worker独立health：enabled_count、last_success、每流expected/computed、pending捕获、oldest_pending、gap、阻塞原因、核对状态。
休市或disabled不能算lagging；有心跳不等于完成计算。日志只输出安全身份/错误码，不输出凭据或完整输入。
初版reference health独立展示，不擅自改变当前总Runtime health聚合规则。
部署脚本提供render-only与默认关闭的worker配置；不在import时连接DB/Redis或启动循环，不动现役服务。

## 10. 开发任务与验收

### T1：合同、activation与schema增量

文件：`openspec/specs/reference-trading/spec.md`、`app/reference_trading/activation.py`、`models.py`、新增Alembic revision。
- [ ] 明确capability/model接受/启用状态，修正canonical中P5仍写未实现的过期引言，不能提前写P6 active。
- [ ] 实现严格activation plan/dry-run/受控apply，seed/FLAT/generation和禁用互斥。
- [ ] 新增 `tests/reference_trading/test_activation.py` 与迁移测试；覆盖过期计划、依赖漂移、禁用竞态和无生产副作用。

### T2：capture与forward service

文件：`app/reference_trading/capture.py`、`forward_service.py`、现有repository/contracts/checkpoint。
- [ ] 复用六表加入durable pending capture，严格大小/hash/唯一约束；不推进seq。
- [ ] ForwardReferenceService消费capture，复用PreparedBatch提交与presentation。
- [ ] `test_forward_capture.py/test_forward_service.py`：捕获后crash、commit前后crash、重复/冲突、两个writer、未知提交核对、无信号mark。

### T3：typed输入、调度与恢复

文件：`forward_inputs.py`、`runtime.py`、`composition.py`、CLI reference入口、现有market读取公共入口。
- [ ] 实现Session完成输入与来源资格；单worker、公平轮转、扫描和预算；生产开关默认关闭。
- [ ] `test_forward_inputs.py/test_forward_runtime.py/test_forward_recovery.py`：跨夜、短桶、停机有无capture、owner切换、无信号、禁用后旧计算不能提交。
- [ ] 历史预热和forward起点隔离，Newow HOLD首个CLEAR保留NO_OBSERVED_ENTRY。

### T4：盘后核对和健康

文件：`reconciliation.py`、runtime health/deploy组合；只在必要时修改after-market轻量唤醒入口。
- [ ] matched/mismatch/pending与P4只读计划，源修订不静默自动rebuild；不阻塞行情成功事实。
- [ ] `test_forward_reconciliation.py/test_reference_runtime_health.py`：维护锁busy、信号唤醒丢失、休市、旧输入修订、隔离故障。

### T5：HTDY first_seen候选适配

文件：`guiyi_quant/reference_trading/htdy.py`、strategy_checkpoint、共享纯评价seam（如需抽取）。
- [ ] 实现§8模型、窗口与checkpoint，不复制或修改HTDY公式。
- [ ] `test_htdy_reference_model.py/test_htdy_reference_repainting.py`：买卖反手/同向/冲突、未来重绘、恢复幂等、未接受模型不可生产activation。
- [ ] 回归现有Alert evaluator/runtime，证明Event数量、first_seen、one-shot transport语义不变。

### T6：forward查询与页面闭环

文件：现有query/presentation/API/schema、公共reference composable/panel、HTDY/Newow/Subing workspace。
- [ ] 引入forward模式、snapshot资格、交易和统计；原historical默认不变。
- [ ] `test_forward_query.py/test_forward_api.py`和Web相应测试：observed_at未来泄漏、分页时反手、未启用、gap、核对差异、模式切换取消、GET零计算零写入。
- [ ] 隔离真实API/Web验收，HTDY图表回看与observed列表明确区分。

### T7：组合验收、独立Review与集成

- [ ] 先定向单测，再P0–P5回归与Alert/Live受影响组；真实隔离PG验证事务/迁移，专用Redis验证需要的实时读取。
- [ ] 使用固定fixture和假时钟做确定性恢复/竞态；不得用mock声称生产已验。
- [ ] 单流、60品种、多策略基准实测预算、处理延迟/内存/存储；不虚报自然运行能力。
- [ ] 对时序、模型、并发和migration安排独立Review；修复Confirmed Issue后再集成develop。
- [ ] 提交/push任务分支，按当前集成流程合入develop；只暂存本任务文件；不发布或启用。
- [ ] 最终列出实际测试、代码/Review状态、模型接受与全部外部Gate；源码完成不等于Runtime ready。

依赖：T1 -> T2 -> T3 -> T4；T5依赖T2/T3；T6依赖T2/T5；T7依赖全部。
若上游基线有既有失败，先在未改动基线复现并报告，不通过删断言造绿；真正影响本任务的缺陷需范围内修复。

## 11. 测试入口和交付边界

新增文件后先 `rg --files` 核对路径。参照 TESTING.md，示例命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/reference_trading
git diff --check
```

PG/Redis只使用TESTING.md约定的显式一次性隔离实例，禁止读生产.env“借库测试”；skip如实列待验。
Web定向node测试及build按现有工程命令；OpenSpec、secret scan、Ruff与相关类型检查按变更范围运行。

独立Review重点：disabled后悬挂提交、观察时间伪造/泄漏、capture没有原子消费、HTDY重绘误改历史、
历史/forward source proof串用、seed携入历史OPEN、D1/W1未完成输入、reader切换隐含启用、修订自动越权。

本次目标是CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE并具备develop集成条件。
剩余生产Gate：模型正式接受、schema升级、精确forward scope和起点、预算与恢复策略、query切换、版本发布/Runtime promotion、自然运行证据。
这些不由开发任务自动完成，不复用RB试点旧授权，也不影响原15m苏冰通知范围。
