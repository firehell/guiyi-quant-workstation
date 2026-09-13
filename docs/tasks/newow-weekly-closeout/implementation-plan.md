# Newow Weekly Engineering Closeout Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans，逐任务 TDD 实施。用户已要求设计后直接交 Sol high 开发，
> 不重复请求同一普通开发批准。真实 mutation、拒绝后的重试仍遵守单独 Gate。

**Goal:** 完成发布以外的周线工程与验收收尾，交付可审的 60×3 矩阵和精确缺口，而非制造全 READY。
**Architecture:** 复用 NewowReadinessAudit/MDS/ContractWarmupPlanner 和现有 UI；只增加小型验收脚本与离线测试。
**Tech Stack:** Python/pytest/SQLAlchemy readonly、Vue/TypeScript/node:test/Playwright。
**Spec:** [设计](design.md)，必须完整阅读。

## 全局约束

- 代码起点至少包含 develop `9604a0d720cc31f2ac39d281a6613378c0bd2cd5` 与 CLEAR v2 `f32bac897`。
  本设计/计划来自交接 final docs commit；新树默认可能从 main 起，先引入完整 develop 依赖再取文档。
- UI 分支当前在活动合并中，按设计 UI_IMPORT_PENDING 处理；禁止修改源 `0460` 的 dirty/index/MERGE_HEAD。
- operational 60、frequency=1w、as_of=2026-09-13T06:36:13+00:00；main矩阵180，D1只作为既有companion。
- RELEASE_STAGE、公式版本、v2 reference/schema、profile/futures adaptation 不改。未开放能力保持未开放。
- 不设计/执行最终发布；不 provider/生产数据写入/Scope/通知/Runtime。不得重做两次成功 PT apply。
- 所有执行命令只维护在 TESTING.md，新增“Newow 周线剩余工程收口”小节，本计划指定行为与验收。

## Task 1：确定性 PT 检查器和离线 readiness 摘要

**Files:** Create `scripts/newow_weekly_acceptance.py`；Create
`services/quant-api/tests/newow/test_weekly_acceptance.py`；Modify `TESTING.md`。
**Consumes:** typed chart/reference results、完整 `data.newow-readiness` JSON、冻结 operational product tuple。
**Produces:** `validate_pt_initial_clear(chart_result, reference_result) -> dict` 与
`summarize_readiness(report, expected_products, expected_as_of) -> dict`，两个 CLI 模式 pt/summary。

- [ ] 先 RED：构造真实域类型 fixture，`FeatureRuntimeStatus.READY` 必须通过；warming/unavailable/None拒绝。
  同 snapshot v2 的 PT2610 新资格 CLEAR 无关联交易成功；token空/不等、错误资格、related、sequence、伪Trade失败。
  其他 owner 的真实 BUILD/Trade 不导致失败；可见图表被裁剪不允许检查器重新推断生命周期。
- [ ] 补 result 身份负例：错 product/strategy/frequency/series/profile/formula/as_of/section、未delivered、
  空value、错合同组或不兼容generation均拒绝。两份meta固定pt/main_rise/1w/actual_dominant/冻结截点；
  data_revision_identity遵既有None合同，input_content_sha256不因chart/reference窗口不同被错误要求相等。
- [ ] 写最小纯检查实现，分开 typed READY 与 readiness wire 大写 READY，不添加大小写宽松兼容：

```python
if chart_result.chart.status is None or chart_result.chart.status.status is not FeatureRuntimeStatus.READY:
    violations.append("CHART_NOT_READY")
if reference_result.reference.status is None or reference_result.reference.status.status is not FeatureRuntimeStatus.READY:
    violations.append("REFERENCE_NOT_READY")
```

- [ ] 脚本 pt 模式使用既有 SessionLocal/readonly_transaction 和 reader/service composition，固定pt/1w/as-of；
  一次读取后检查并序列化，失败也输出安全 violations，非零 exit，不打印异常stack/SQL/连接串。不在导入时建连接。
- [ ] 离线 summary RED：重复/缺case、scope/as-of不同、fake计数、null写入计数、matrix=false、compact输入拒绝；
  180case中只有3 READY返回3，不返回180；known gap但audit complete必须与业务ready分离。
- [ ] 增加伪 complete/status 测试：顶层声称audited/true但枚举、dependency、repair或section有UNKNOWN/
  UNSTARTED，或budget_exhausted=true必须拒绝。用现有readiness规则重算并核对，不另定义较松的完整标准。
- [ ] 最小实现按 `(symbol,strategy,frequency)` 集合核验、重新统计、原生reason分组；不创建第二份repair planner。
  不信任自报main_ready_count；缺字段显式失败。对 UNSTARTED/UNKNOWN/budget及未开放状态分别测试。
- [ ] 离线测试确认任何 summary路径不建 Session、不初始化provider；PT路径只用readonly事务，异常仍释放资源。
  运行新增测试、readiness/CLI/read-only兼容测试，绿后提交，不提前执行现场probe。

## Task 2：整合作者完成的 UI 候选

**Files:** Inspect/merge `apps/quant-web/src/components/market/detail/`、`src/composables/useMarketDetailController.ts`、
`src/utils/marketDetailRoute.ts`、`src/pages/market/MarketDetailPage.vue` 与该依赖现有tests/e2e；
保持 CLEAR v2 的 types/parser/Workspace/primitives、DECISIONS/PROJECT_SOURCE/ARCHITECTURE。
**Consumes:** 当前develop + 作者最终 clean/reviewed UI commit，最小已知需求集合 be6021f8。
**Produces:** 同一隔离分支中完整 UI + CLEAR v2，没有冲突标记与功能丢失。

- [ ] 定位真实 UI 作者任务/当前 worktree，检查 HEAD、MERGE_HEAD、dirty、Review。活动合并时不接管；
  向作者做依赖协调或等待完成，Task1可继续。没有实际任务可协调时保留UI pending，不猜测完成。
- [ ] 作者完成后冻结 commit；develop 已包含则跳过重复引入，否则在本树整合该提交。记录source base/head。
- [ ] 对本树产生的冲突先补失败测试：统一导航保留选择/返回状态，三策略overlay不同，旧legacy UI不复活，
  CLEAR无入场label/details保留，正常reference文字准确；再作最小语义合并，不能整文件选边。
- [ ] 完整 Web unit/build及市场详情/Newow fixture E2E；新增小chart_limit初始CLEAR仍可见/无伪交易测试。
  既有截图只因明确UI需求变化而更新并实际查看，不更新阈值躲失败。
- [ ] 合并后独立Review过关，记录最终代码身份。若UI仍pending，不能声称本任务全部集成完成。

## Task 3：现场 PT 收口与全量 matrix（独立只读阶段）

**Files:** Use existing `services/quant-api/app/market_data/newow/{readiness.py,readiness_composition.py}`；
`app/guiyi_cli/{main.py,data_commands.py,data_parser.py}`；新验收脚本；本次显式本地 evidence 目录。
**Consumes:** 完成Task1/2的固定代码、scope/window hashes、合法只读连接。
**Produces:** PT accepted或真实失败输出；完整60×3 readiness report与同源离线摘要。

- [ ] 先preflight：本树import路径/commit、维护是否忙、scope精确60、as-of固定、readonly入口无provider。
  不查看凭据值；权限缺失仅阻塞现场，其他工作继续。旧任务的失败不直接重跑，本轮新明确范围仍服从宿主批准。
- [ ] 在获准连接下执行一次新pt模式，核对结构化输出与退出码；保留旧检查器exit1原因与新证据，不更改旧日志。
- [ ] 用现有CLI执行一次 operational/1w/matrix/max-work100000/timeout1800 的全量审计；记录完整stdout和
  exit/耗时/代码/scope hashes，遇忙不抢占正式维护。禁止compact再触发一次查询。
- [ ] summary模式读取同一完整JSON，校验exact180cases；统计chart/reference/联合READY及各section限制。
  audit incomplete、预算耗尽、UNKNOWN照实保留，不删case，不自动循环重试或加预算。
- [ ] 对真实页面做有界本地候选回读：PT、一个正常有trade样本、一个gap/source样本，若样本存在；
  使用candidate只读API且关闭provider/Alert/后台任务，空闲端口，不复用正式服务。不以fixture替代真实数据页面。
  若candidate只读服务权限不足，单独标记browser field pending，既有fixture验证仍有效但不混淆。

## Task 4：按最新结果修复工程与形成精确数据方案

**Files:** Only if reproduced: `readiness.py`、`readiness_composition.py`、`product_reader.py`、
`product_service.py`、`services/quant-api/app/market_data/diagnostics.py` 与直接相关测试；
参考既有 `historical_data_manager.py`、data canonical，不改其事实定义。
**Consumes:** Task3完整report的原生dependency/repair/metadata rows。
**Produces:** 已修代码缺陷及测试；一个下一安全数据批次proposal或“无安全candidate”的准确结论。

- [ ] 按code/reason区分工程bug、missing、metadata UNKNOWN、source/integrity、正常不足，不用旧907目标执行。
- [ ] 每个复现工程bug先加最小RED并确认失败，再修唯一authority入口、GREEN、影响回归。若触及新公式/收益/
  metadata完整性语义，停该项提出差异，不静默调整；其余任务继续。
- [ ] 用现存只读事实复核PF2611零价和RS冲突；不得重新下载试错、替换零价、默认缺Session或放宽fail-closed。
- [ ] 提取原生ContractWarmupPlanner计划，按contract/frequency/window去重并保留全部消费者和planhash。
  缺metadata优先使用既有 `metadata-repair --phase plan` / `bounded_metadata.plan_metadata` 形成精确日范围方案，
  不进入 fetch/apply；未知Calendar分类后的Session计划按原合同分阶段，不推断夜盘。相关变更加
  `services/quant-api/tests/data_foundation/test_bounded_metadata.py` 回归；有source/integrity从普通补数中排除。
- [ ] 最小数据批次写明scope、预期bars/requests、影响、dry-run、幂等、失败/未知结果停止及恢复方式。
  900MB只作将来批准下载的上限，不按PT样本线性估流量。没有合格目标就不生成虚假建议。
- [ ] 本轮不apply。因代码修复需要现场复跑时请求新的精确意图，保留原始失败，不能循环直至绿。

## Task 5：文档/Evidence、独立 Review 与本地集成

**Files:** `STATUS.md`、`TESTING.md`、`outputs/newow-weekly-60-20260913/{README.md,readiness-summary.json}`；
`docs/tasks/newow-initial-clear/implementation-plan.md` 的执行结果段；相关active OpenSpec仅有合同变更时更新。

- [ ] 索引引用新完整证据hash/明确路径与code/as-of/scope；保留旧apply不可变字段，不覆盖旧raw报告。
  新生产明细默认本地不上传；不能声称仅保留/tmp/hash就是长期完整evidence。检查文件写入/secret边界。
- [ ] 同步旧“PT未验收/2of3”叙述到实际新结果；exit1保留为历史误报，未获准现场时不得写accepted。
  分别记录CODE/TEST/REVIEW/develop、PT、audit遍历、180覆盖、READY数、待批准数据操作。
- [ ] 最终按TESTING执行：新增acceptance/readiness/CLI，完整Newow+工程、受影响data模块，完整Webunit/build，
  相关fixture E2E，OpenSpec/secret/diffcheck；真实browser与单元结果分别记录。无关全仓测试不机械重跑。
- [ ] 独立reviewer给exactbase/head和真实结果，检查fail-closed、计数/边界、UI合并、证据矛盾和越权路径。
  修复blocking findings并同reviewer复审；禁止把业务缺口降级成文案已知限制以伪装完成。
- [ ] 本地task提交与条件满足的develop集成，保留其他任务dirty；不清理来源/Runtime工作树。
  本地集成可完成，含生产证据的远端上传若被拒不重试，不修改远端/全局配置。
- [ ] 交付各层真实状态与唯一最小下一步；数据Gate存在时报PARTIAL，不生成发布计划、不请求发布批准。

## 验证命令维护要求

新增 TESTING 小节包含新脚本两个模式的实际usage、离线新增pytest及已有readiness/CLI tests、Task3完整CLI
固定参数、Webunit/build与market-detail/newow-product/newow-detail-light/newow-chart-panes E2E命令。
命令先验证 --help/parser，不抄不存在的flag；不得把命令可运行等同数据可用。实际fixture期望从上述行为表逐项断言。
