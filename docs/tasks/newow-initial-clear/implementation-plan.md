# Newow Initial CLEAR Without Entry Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the Sol high task.
> 用户已要求完成设计/计划 review 后直接安排实施；不再为同一设计、写测试、编码或本地提交重复确认。

**Goal:** 展示经过证明的主升浪初始无入场 CLEAR，保持零伪造 BUILD/ReferenceTrade，并交付 v2 typed 合同。

**Architecture:** 唯一 reader 签发并绑定已验证 lifecycle evidence，纯策略 adapter 识别唯一初始转换，
ReferenceTradeProjector 独立验证 evidence/frame/action。
API 和 Web 成套迁移到 v2；沿用唯一 MDS reader、现有分页、统计和 UI，不新增 provider 或账户模块。

**Tech Stack:** Python / dataclasses / Decimal / FastAPI / Pydantic；Vue / TypeScript / Lightweight Charts；pytest / node:test / Playwright。

**Spec:** [设计](design.md)。执行前完整阅读。

## 全局边界与输入

- 代码依赖提交 `85b6d42f8c561e8f3043a583e3a6433ae45d2c05`，设计初稿 `d7cdbb0cb`；使用交接消息中的最终文档提交。
- 新任务先读 AGENTS、STATUS、docs/DEVELOPMENT、上述 spec、active newow-product-reference-trading OpenSpec；
  核对 branch/HEAD/dirty/worktree 与当前 develop，保留所有不属本任务的改动。
- 新建任务的默认基线若尚不含文档提交，从同一本地 Git object database 读取/引入交接提交，保留其完整依赖；
  不用 cherry-pick 单个文档提交来假装依赖代码已在树中，不使用 reset/force update。
- 固定依赖顺序：当前 develop（已含 UI unification `a755b0694`）→ 趋势点
  `faa963d2a717f4cd2127ca8edb145ad9f1352afa`（替代初审 `a83dd60e`）→ CLEAR v2。先检查祖先关系；若趋势点尚未合入 develop，
  在新实施分支显式整合该 exact commit，核查其 Review/测试结果，然后才修改共享 API/Web/OpenSpec 文件。
  若作者已修订，协调替代 exact commit；不要自行覆盖或退回旧趋势点行为，独立 Core 工作可继续。
- 只有本地实现、离线验证、独立 Review、commit 与条件满足的本地 develop 集成属于执行范围。
- 上轮两次 PT apply 已成功且授权耗尽；禁止重做、扩大补数、provider 请求、metadata/DB/Canonical/Redis 写入。
- 原任务的远端 push 曾被自动审批拒绝（生产证据上传尚未获明确授权）；不得重试该上传。其余独立工作继续。
- 旧 `/trend-detail`、HTDY/SuBing/Free、公式金样、MAIN_RISE_PAGE_V1、futures adaptation、profile、Action/Hint ID 不变。
- 本功能不增加可持久化策略状态、兼容 reader、后台任务、独立账户/交易事实，也不开放 D1/60m/explanation。
- 测试命令统一写入并执行 `TESTING.md` 下“Newow 初始无入场 CLEAR v2”小节；本计划只定义测试组与验收。
- 若有环境/真实只读 Gate，先完成离线任务，单独披露现场证据缺口；fixture 结果不可冒充 PT 现场。

## Task 1：真实初始转换与结构合同（Core）

**Files:**
- Modify: `packages/quant-core/guiyi_quant/newow/product_contracts.py`
- Modify: `packages/quant-core/guiyi_quant/newow/product_adapters.py`
- Modify: `services/quant-api/app/market_data/newow/product_reader.py`
- Modify narrowly: `services/quant-api/app/market_data/newow/product_service.py`（仅 evidence 传递，先完成趋势点依赖整合）
- Test: `services/quant-api/tests/newow/test_product_adapters.py`
- Test: `services/quant-api/tests/newow/test_product_contracts.py`
- Test utility: `services/quant-api/tests/newow/product_fixtures.py`
- Test: `services/quant-api/tests/newow/test_product_reader.py`, `test_product_service.py`

**Consumes:** `step_main_rise`、MDS 验证的完整 ProductBar prefix、现有 `_PairingState` 和 StrategyAction。
**Produces:** `TradeEligibility.INITIAL_CLEAR_NO_ENTRY`、`LifecycleReplayEvidence`；接口为
`replay_strategy(identity, bars, *, lifecycle_evidence=())`，StrategyReplay 保留绑定后的 evidence。

- [ ] 先写 RED：裸 tuple/缺 evidence 的孤立 CLEAR 仍拒绝；reader 完整验证成功后经 service 的 replay 成功。
  reader coverage 失败不得签发；截断左前缀、替换 Bar、错 owner/frequency、复用旧 evidence 全部拒绝。
- [ ] 在 product_contracts 定义设计中的 evidence 字段和校验；reader 在既有 MDS coverage 和 rank1 校验
  成功后逐 segment 组装，ProductReadSet 分周期携带，两个 service replay 调用点均传递。只绑定数据，不增加
  第二个 Catalog reader/coverage 推断。合法 as-of 子前缀派生保留原首端并重新绑定数量、末端、指纹。
- [ ] 编写具有手算转换点的无 provider fixture：同物理 segment，35 根 OHLC=100，随后 1 根 OHLC=90。
  前 35 根 MA35=MA45，第 36 根 MA35<MA45，是首个 CLEAR；volume=1、completed=True，bar 时间严格递增。
  用同一 fixture factory 参数化 1w/1d/60m（直接提供周期 Bar，不聚合）；周线用每七天一个合法测试时间。
  synthetic evidence factory 仅供单元测试，服务级成功用例必须走真实 reader 校验链（测试数据源）。
- [ ] 先写消费真实 replay 的失败测试：第 36 根 `kind=CLEAR`、新资格、related=None、sequence=0，无 BUILD；
  frame state=CLEAR，前缀同值同 ID。执行 TESTING 定向组，确认旧 adapter 在 pairing conflict 处失败。
- [ ] StrategyAction 构造仅检查 MAIN_RISE+CLEAR、无 related/source IDs、sequence=0；StrategyFrame 构造
  检查 eligible/completed、identity/time、main_state=CLEAR 和唯一包含。新增字段不进入 formula kernel 或行情模型。
- [ ] adapter 加一个有界私有初始转换资格状态，随 segment 初始化/重置。输入 state 前带 YELLOW、输出 BLUE、
  所有过去状态有效且无转换、buy price/bars 为空、signal profit/hold 为空、无 pairing entry 才可输出新资格。
  核心分支形状如下（变量由实际状态实现绑定）：

```python
if verified_lifecycle and first_yellow_to_blue and no_entry_in_state_and_pairing:
    action = _new_action(
        identity, product_bar, ActionKind.CLEAR, result.band_signal.price, 0,
        trade_eligibility=TradeEligibility.INITIAL_CLEAR_NO_ENTRY,
    )
else:
    action = _pair_action(pairing, action)
```

- [ ] 任何真实转换（含非 eligible 前缀）消费资格。不要只用 `eligible_build is None` 推断无历史；曾关闭的
  BUILD 或消失的 warm-up witness 不能恢复资格。无效 state 消费资格，不假装重新初始化。
- [ ] 把旧 `test_main_rise_requires_a_real_prewarm_build_witness_for_an_isolated_clear` 的“真实初始 CLEAR
  应抛错”部分改成新规则；保留 warm-up BUILD witness 的原断言。不要放宽 trend/oscillation 裸 CLEAR 测试。
- [ ] 补负例：伪 CLEAR（前后都黄）、nonempty profit/hold、重复 CLEAR、初始 CLEAR 后完整交易再伪 CLEAR、
  非 eligible CLEAR、错误策略/related/sequence/source；补 owner 切换和 warm-up CLEAR 后真实 BUILD/再次 CLEAR。
- [ ] 定向绿后运行主升浪 page-v1 金样和 replay invariants；MA/Hints 的逐值金样保持原样，记下真实结果。

## Task 2：无交易投影、独立证据验证与因果性

**Files:**
- Modify: `packages/quant-core/guiyi_quant/newow/reference_trades.py`
- Test: `services/quant-api/tests/newow/test_reference_trades.py`
- Test: `services/quant-api/tests/newow/test_reference_interruptions.py`
- Test: `services/quant-api/tests/newow/test_product_replay_invariants.py`
- Test: `services/quant-api/tests/newow/test_reference_statistics.py`

**Consumes:** Task 1 完整 StrategyReplay；既有 OwnerBoundary/as_of。
**Produces:** `ReferenceProjection(trades=(), diagnostics=("INITIAL_CLEAR_NO_ENTRY",), ...)` 对初始-only 样本成立。

- [ ] 写 RED：真实 Task 1 replay 投影无交易，初始诊断存在，所有交易数=0，win/mean/sum=None。
  断言不经被测函数计算期望；测试必须能发现“生成伪 BUILD 或零收益交易”的错误。
- [ ] 参考投影器新分支置于正常 eligible 配对之前，但不得绕过 owner boundary 校验。
  独立校验 replay lifecycle evidence 与 segment/frame 输入身份、首尾、数量、指纹一致；缺 evidence、左侧
  截断、action-only、篡改数据以及过期 evidence 一律拒绝，不接受上游诊断或 complete 布尔值代替证据。
  建立一次 segment/frame/action 索引，要求当前 action 精确对应 eligible position；frame 完整前缀此前均有效黄带、
  当前首次蓝带/CLEAR 且 price=ma45；prior Action 不存在。保留当前构造器之外的独立信任边界验证。
- [ ] 用 typed replay 中现有 MA 值验证一致性，不重跑内核。验证失败使用既有 pairing conflict，不公开内部细节。
  缺 frame、非 eligible frame、只有 action、参考价不等 MA45、先前蓝带、伪造 related、重复或跨 owner 均拒绝。
- [ ] 先剔除 replay 上游同名诊断，仅在成功验证本时点 Action 后加入一次；`bar_end>as_of` 不能影响当前诊断
  或判定。诊断名称不作为接受证据。
- [ ] 写并通过后续正常交易例：`[100]*35 + [90] + [110]*60 + [80]`，literal 预期 Action 索引 35 CLEAR、
  36 BUILD、96 CLEAR；初始 Action 不投影，后两项投影恰好一笔 CLOSED。对三周期做 prefix/as_of/restart replay。
- [ ] 增加 first transition 在 warm-up 的场景：它不输出；后续 warm-up BUILD 与 rank1 CLEAR 仍走
  `NO_ELIGIBLE_ENTRY`。旧 owner open trade 与新 owner 初始 CLEAR 只产生旧 owner interruption，不交叉配对。
- [ ] 完整 replay 以初始 CLEAR 之前的 as_of 投影等于相应短 prefix 投影；注入的上游诊断不得出现。
  cutoff==bar_end 可以出现，cutoff==owner boundary 不能把退出后的动作视为本 owner。
- [ ] 定向绿后运行所有 ReferenceTrade/statistics/interruptions/replay tests。无关收益、initial_before_window
  membership 和 Decimal context 不修改。

## Task 3：v2 协议与旧缓存/cursor 隔离

**Files:**
- Modify: `packages/quant-core/guiyi_quant/newow/product_identity.py`
- Modify: `services/quant-api/app/market_data/newow/product_service.py`
- Modify: `services/quant-api/app/schemas/market_newow_product.py`
- Inspect/modify only if needed: `services/quant-api/app/api/market_newow.py`
- Test: `services/quant-api/tests/newow/test_market_newow_product_api.py`
- Test: `services/quant-api/tests/newow/test_product_service.py`
- Test: `services/quant-api/tests/newow/test_product_snapshot_cache.py`
- Test: `services/quant-api/tests/newow/test_product_readonly_compatibility.py`

**Consumes:** Task 1/2 domain results；现有 ProductResultMeta、page identity、dependency proof。
**Produces:** typed `newow_product_detail_v2` 与 `newow_marker_reference_zero_cost_v2`；新资格 wire value。

- [ ] RED：通过真实 API serialization fixture 验证 v2 envelope、新资格；用同输入分别冻结旧/新合同得到旧 cursor，
  v2 请求携带旧 chart 或 reference cursor（不带 snapshot_token）被拒绝。覆盖带旧 token 的请求。
- [ ] 升级共享 REFERENCE_MODEL_VERSION 和服务/响应 schema；保留全部 kernel version/profile/futures adaptation。
  三策略参考交易 ID 均进入 v2 namespace，原 BUILD/CLEAR signal ID 和数值保持。既有 v1 历史报告原样保留。
- [ ] 将 `(SCHEMA_VERSION, REFERENCE_MODEL_VERSION, FUTURES_ADAPTATION_VERSION)` 绑定至 common cache identity、
  dependency proof 与 `_page_identity`。不要只改默认 token 检查，遗漏无 token 的 opaque cursor。
  `_fingerprint` 继续是输入内容，不能把合同变动伪装为行情变动。
- [ ] API 新资格限制通过 Pydantic 和域结果约束实现；handler 仅序列化，不复制配对逻辑。
- [ ] 行为测试：同 v2 entry 的 OPEN→CLOSED/图表裁剪仍同 ReferenceTrade ID；v1/v2 IDs 不同而收益相等；
  schema-reference 混配失败；旧 `/trend-detail` 保持原响应；capability 和历史选择 schema 不升级。
- [ ] 正常同版本 snapshot/chart-reference 恢复、历史定位、分页续接仍通过。完整 reference replay 必须在
  viewport/history-limit 过滤前调用 projector；不得裁剪后再推断初始动作。

## Task 4：Web 严格解析与可见的“无入场”事实

**Files:**
- Modify: `apps/quant-web/src/types/newowProduct.ts`
- Modify: `apps/quant-web/src/utils/newowProductTypes.ts`
- Modify: `apps/quant-web/src/components/market/detail/newow/newowProductChartPrimitives.ts`
- Modify: `apps/quant-web/src/components/market/detail/newow/NewowProductWorkspace.vue`
- Inspect/modify when necessary: `apps/quant-web/src/composables/useNewowProduct.ts`
- Tests: `apps/quant-web/tests/newowProductTypes.test.ts`, `newowProductChartPrimitives.test.ts`,
  `NewowProductChartStage.test.ts`, `useNewowProduct.test.ts`, `newowReferencePanel.test.ts`
- E2E: `apps/quant-web/e2e/newow-product.helpers.mjs`, `newow-product.spec.mjs`

**Consumes:** Task 3 v2 payload；现有 action marker/selection/dialog flow。
**Produces:** typed eligibility 保留到 marker model；“清仓（无入场）”及详情说明；参考表无该 Action 对应交易。

- [ ] RED：parser 接受 v2 新资格，拒绝 v1/混合版本与错误 kind/strategy/related/sequence；Marker 文案和选择详情
  保留资格，不能丢失后退回普通清仓文案。图表页被裁剪时 parser 不要求完整前缀。
- [ ] 仅迁移 active Newow typed 元数据与测试 fixture 的版本字面量；不要替换 SuBing reference version、
  capability/historical selection version、策略 profile 或不可变历史 evidence。
- [ ] 新资格在 parser 结构验证后进入 `NewowProductActionMarker.tradeEligibility`；marker 与动作详情复用
  一个局部文案 resolver，显示设计中的 label/explanation。沿用已有箭头、价格、Bar time、owner/segment。
- [ ] 检查 UI 两行摘要、当前/历史动作选择、参考卡片是否还把该状态描述成“已成交/已卖出”；必要时只改该资格
  的表达。action 弹窗正常显示原始信号与资格；zero-trade 不制造一行“0%”。
- [ ] 补实际 parser→marker→组件或浏览器路径测试。UI snapshot 捕获 v2 fixture、点击 Marker 可达详情；
  后续真实交易正常展示与定位，初始 Action 不计入统计。
- [ ] v1 迟到响应被拒绝并使相关缓存状态不可用；version proof 变化清理旧 selected trade/signal、分页/cursor。
  同 v2 token 不因 viewport 改变而丢失合法 reference state。不要扩建持久缓存框架。
- [ ] 确认趋势点 exact dependency 已在本分支，复测趋势点 API/parser/marker/composable/E2E 以及 v2 的共享路径；
  集成前核对该任务后续提交，协调保留已通过的展示行为，不在两条独立分支分别覆盖同一份旧 payload。
  运行定向 Web tests、完整 Web unit、build，再跑 TESTING 中 Newow 三个 fixture E2E 文件，禁止自动更新截图。

## Task 5：Canonical、验证命令与现场证据

**Files:**
- Modify: `openspec/specs/newow-product-reference-trading/spec.md`
- Modify narrowly: `DECISIONS.md`, `PROJECT_SOURCE.md`, `TESTING.md`, `STATUS.md`
- Update after fresh acceptance: `outputs/newow-weekly-60-20260913/readiness-summary.json` and `README.md`

- [ ] active OpenSpec 增加新资格、历史/时点证明、投影不产生交易、v2 兼容和旧接口保留场景；修订 MACD 小节
  “顶层 v1 保持兼容”与 v2 的冲突，保持 MACD 分支内 shape/参数/hash 不变。
- [ ] DECISIONS 与 PROJECT_SOURCE 只记录新接受的动作资格/投影边界；不改“主动作只有 BUILD/CLEAR”。
  STATUS 把“尚待 owner 选择”改成获批实现状态，测试/Review/现场结果完成后逐层补证据。
- [ ] TESTING 添加单一小节：Core/Reference 定向组；API/cache 组；Web 定向/unit/build；fixture E2E；
  OpenSpec/secret/diff 与工程一致性。命令使用已存在环境和显式本树 PYTHONPATH，缺依赖按环境流程处理。
- [ ] 只读 PT 验收作为独立有界阶段：固定旧 as_of、symbol=pt、frequency=1w、matrix、max-work=10000、
  timeout=300，使用既有 newow-readiness CLI，完整 report 保留摘要/hash。执行前确认 candidate imports 指向
  本次源码，依赖 readiness 仍 6 DATA_READY，provider/writes=0；错误/权限不足不得触发补数。
- [ ] 检查 main_ready_count=3/3、main_rise chart/reference 无 pairing error，实际初始 CLEAR、新资格、
  无伪 BUILD/Trade；比较器正常样本不足/NOT_APPLICABLE 与 explanation UNOPENED 仍保留。
  CLI 汇总不足以证明 Action/Trade 时，以同 MDS reader/product service 做一次有界只读查询补齐输出证据。
- [ ] 若生产只读权限未获宿主允许，保留 `EXTERNAL_GATE_PENDING` 并继续完成离线验收/commit/Review。
  不把旧 DATA_READY 或 reviewer 上轮输出视为本次 v2 现场通过；不启动/切换正式服务。

## Task 6：最终独立 Review、修正、集成与交付

- [ ] 自审全部 diff 与设计验收条目；检查 secret、无关文件、Canonical/DB/公式改动、版本替换误伤。
- [ ] 运行 TESTING 规定的受影响检查。全 Newow 后端和 Web unit/build 因共享版本变更必须覆盖；其他
  全仓库测试仅在集成冲突或新的影响证据需要时追加，不机械反复运行。
- [ ] 使用一位独立 reviewer，给 exact base/head、设计/计划、测试输出与现场边界。要求核查完整前缀证明、
  warm-up 消费资格、未来诊断、owner boundary、无 token 旧 cursor、ID namespace、Web 空态和既有消费者。
- [ ] 修复 blocking findings，定向重测并由同 reviewer 复审；测试不通过不得提交“已完成”状态。
- [ ] 生成 task commit；确认 develop 没有并发重叠未提交修改，以非破坏方式整合新 develop 并复测冲突路径，
  然后完成已授权的本地 develop 集成。不得覆盖其他 worktree，也不删主工作树。
- [ ] 交付 CODE/TEST/REVIEW、本地集成、PT现场证据分别的状态和 exact commit；注明远端 push 未执行及原因。
  最终结论只覆盖实际完成层级：允许集成 develop；不自动发布或晋升 Runtime。

## 计划复核记录

设计审查与计划审查由主任务和同一位独立 reviewer 完成；最终修订与 review 结论以文档交接提交和主任务记录绑定。
实施开始后，复用现有计划，不重新要求 owner 批准已经确定的 A 方案。只有新发现会改变公式、收益口径或外部
操作范围的重要歧义才停受影响部分，其余安全的已授权工作继续。

## 执行状态

- 离线实现、定向/模块回归、Web build、fixture E2E、OpenSpec、secret scan、diff check 与独立 Review 修正已完成。
- task commit 已生成；Review 修正与本地 develop 集成状态以 Git history 和最终交付记录为准。
- 固定 PT 截点的生产只读验收因宿主凭据权限 Gate 未执行，保持 `EXTERNAL_GATE_PENDING`；未更新 readiness output。
- 未执行远端 push、main/tag/Release、Runtime、通知、provider、Canonical、数据库或 Redis mutation。
