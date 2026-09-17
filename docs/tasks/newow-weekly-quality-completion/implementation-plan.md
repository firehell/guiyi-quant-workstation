# 牛哇周线质量分段与 60 品种补全 Implementation Plan

> **For agentic workers:** 使用 `superpowers:executing-plans` 在同一个 Sol medium 会话逐任务执行。
> Owner 已认可设计并要求开始实施；不重复询问“选哪种执行方式”或再次批准设计。

**Goal:** 完成 operational 60 品种的 W1 三策略质量分段、依赖补全、真实页面验收，并保留 D1 已有闭环。

**Architecture:** RQData/Canonical/Catalog/MDS 维持唯一事实链；共享周线质量分类解释 D1 来源缺价，
Newow reader 和现有 core 分段/参考投影消费该证明。原生 planner/campaign 执行精确恢复；产品 capability
只在候选范围开放 D1/W1，并将数据写入、release 和 Runtime 列为独立 Gate。

**Tech Stack:** Python、Decimal、现有 PostgreSQL Catalog/Parquet、FastAPI、Vue/TypeScript、pytest、Playwright。

**Spec:** [design.md](design.md)。必须完整阅读，特别是第 4–7 节的覆盖、NO_TRADE、时间和版本约束。

## Global Constraints

- 本任务只实施已认可的周线完整周/缺价中断/恢复预热规则，不改三策略公式、参数或参考收益口径。
- 整个任务以 operational 60 为分母；W1 180 组合，D1 180 组合回归；60m 和完整 explanation 仍 UNOPENED。
- 凭据由已有程序安全加载，不打印配置内容；provider 下载和任何生产写入必须有本任务精确授权。
- 行情普通 strict reader 继续 fail-closed；Newow 专用 quality reader 不能成为通用绕过入口。
- 真实来源重复、错合约、缺交易日、未知异常不能用质量分段豁免。
- 原子性只按现有分区/事务边界声明；部分写入失败保留原事实，先读回，不默认重试或删除。
- 模型保持 gpt-5.6-sol，reasoning medium；一个主会话连续负责，独立 Review 根据高风险 diff 进行。
- 当前主工作树存在他人已暂存和未跟踪 evidence，完全避开；不得全量 git add、reset/clean 或接管其他 worktree。
- docs/DEVELOPMENT.md、AGENTS.md、TESTING.md 优先于历史技能/任务中重复审批、固定端口或旧阶段规则。

## 任务 0：执行基线、原生 worktree 与只读盘点（P0）

**输入/输出：** 输入最新 develop、operational scope、当前 reader/window/capability；输出固定身份与截止的
60 品种 W1 dependency 报告及分类、代表样本候选。此时 W1 仍关闭，不能依赖产品 matrix 判数据是否齐全。

**文件：** 阅读 AGENTS.md、STATUS.md、docs/DEVELOPMENT.md、docs/DATA_CENTER.md、TESTING.md；
`data/universe/operational_products.txt`；
`services/quant-api/app/market_data/newow/readiness.py`、`readiness_composition.py`、`product_reader.py`；
`services/quant-api/app/market_data/historical_data_manager.py`；现有 campaign/acceptance 脚本。

- [ ] 确认宿主已创建 linked worktree；不要在里面再建一层 worktree。原生默认若从 main 开始，在该独立工作树
  建任务分支，以最新已核验 develop（含本设计提交）为基础；不要 checkout 或修改主工作树的 develop。
- [ ] 核对 source/status/dirty、当前 develop 依赖及其他 writer。旧 `newow-w1-partial-source-exception`
  工作树只作参考；不整分支回灌，也不采用旧执行代码冒充当前基线。
- [ ] 读取真实 API/数据身份时使用既有安全配置加载。冻结 as_of、各品种最后完整 W1、D1 回归截止、scope
  与窗口。未取得 Calendar/Session 时明确 UNKNOWN，不使用自然日猜测。
- [ ] 在执行树复用已存在的 Python/Node 依赖，避免无关升级或修改用户全局配置。基线只跑直接相关小测试。
- [ ] 先执行单品种 dependency-only smoke，再按设计第 9 节串行覆盖 60；所有子报告保存原生完整 JSON，
  compact 从原报告离线生成。首次 smoke 可纳入总清单，不需要机械重复同一品种。
- [ ] 全部读取走 fresh read-only transaction、timeout/finally rollback；provider 调用禁用，写入为 0。
- [ ] 全量若预算不足，记录已完成和未执行品种及原因，在保持固定范围和真实身份下安排剩余只读部分；
  不抹去旧失败、重新声明全部已跑完，亦不让相关工具自动修复数据。
- [ ] 核对 campaign 输入格式是否支持此次报告组织方式。若不支持，任务 1/4 中修现有适配或跑合法原生全域报告，
  不能传拼装摘要当原生报告。
- [ ] 输出正常、普通缺口、已证实 D1 缺价影响周、其他来源/完整性、metadata 不足；保留消费者与精确窗口。

命令模板使用 pyproject.toml 已定义的 `guiyi = app.guiyi_cli.main:entrypoint`；运行前确认
`NEWOW_GUIYI` 为已安装 guiyi executable 的绝对路径，并从本次权威解析结果设置产品和截止：

```bash
: "${NEWOW_GUIYI:?set verified guiyi executable path}"
: "${NEWOW_PRODUCT:?set one validated operational product}"
: "${NEWOW_AS_OF:?set this audit timezone-bearing cutoff}"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
  "$NEWOW_GUIYI" data newow-readiness --symbol "$NEWOW_PRODUCT" \
  --frequency 1w --as-of "$NEWOW_AS_OF" --max-work 10000 --timeout-seconds 300
```

不得使用 `--apply` 或 `--matrix` 完成这一步的数据盘点。截止等变量由执行者从真实环境解析，原始 invocation
保存实际值，不把本计划的变量名写进 evidence。stdout 可靠保存到本次唯一的原始报告后再进行摘要校验。

**出口：** 新 60 品种范围可核对；当前数据余额不再引用 8/60。现场暂不可读时，明确受阻项并继续隔离工程。

## 任务 1：确定性周线质量分类与覆盖证明（P1）

**文件：** 视职责在 `services/quant-api/app/market_data/weekly_quality.py` 新建有界纯转换；
复用 `source_quality.py`、`coverage_source.py`、`rqdata_adapter.py`、`market_data_service.py`、`storage.py`。
测试新增 `services/quant-api/tests/data_foundation/test_weekly_quality.py`，扩展
`test_infrastructure.py`、`test_catalog_and_service.py`、`test_storage.py`。
同步 data-foundation/canonical-market-storage/market-series-query 相关 active spec 与 docs/DATA_CENTER.md。

**接口职责：** 输入现有 authority 给出的合约生命周期、周/D1 预期端点与固定 revisions 的 D1 Bar/PriceUnavailableFact；
输出正常周、中断周、具体阻断。纯转换不访问 provider、不自行确定交易日、不写数据库。
周中断类型无 OHLC，包含 design 第 5 节全部来源与时间证明；命名可按现有类型风格确定并在后续任务统一引用。

- [ ] 用隔离 fixture 先复现 D1 中存在合法 PRICE_UNAVAILABLE 时当前 W1 读取/聚合失败；记录现有正确失败边界。
- [ ] 添加正常完整周、跨月周、节假日短周、同周多缺价、整周缺价、缺价与普通缺日并存测试。
- [ ] 添加错合约、重复正常端点、正常与质量重叠、坏 hash、未知质量版本、缺 Session/lifecycle 的拒绝测试。
- [ ] 添加未来/未完成周、上市/到期截断、短 owner 零周的原有行为测试。
- [ ] 实现周分类，所有 consumer 复用同一结果。严格按以下不变量，不按数量放宽：

```text
D = authority.expected_daily_endpoints(physical_contract, completed_week)
B = validated_daily_bar_endpoints
Q = validated_price_unavailable_endpoints
require B ∩ Q = ∅
require B ∪ Q = D
if Q is empty: preserve existing weekly aggregation and validation
else: emit one derived weekly interruption; emit no effective weekly Bar
```

- [ ] 证明上游 D1 revision/质量变化使旧证明失效；当前 D1 与已存 W1 不一致时返回冲突。
- [ ] 查询端只读取已存正常 W1；不临时用 D1 聚合返回替代 Bar。普通 MDS 跨缺价周继续拒绝。
- [ ] 精确验证整周 NO_TRADE 与混合零价周。默认保持现有价格口径；若真实混合周需要新聚合语义，
  将精确样本/数值差异作为唯一受影响的 owner 决策项，其余工作继续。
- [ ] 同步实现与 active canonical；不扩大 D1 PRICE_UNAVAILABLE 白名单、不新造假 W1 价格质量记录。

定向验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
  "$NEWOW_PYTHON" -m pytest -q --tb=short -p no:cacheprovider \
  services/quant-api/tests/data_foundation/test_weekly_quality.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_storage.py
```

`NEWOW_PYTHON` 取已核验的虚拟环境 Python 的绝对路径；不将系统 HOME/CODEX_HOME 当任务变量。

**出口：** 正常/缺价/未知三类有可执行反例保护；共享严格读取未放宽；不要求生产数据变化。

## 任务 2：W1 reader、策略分段与参考历史（P2）

**文件：** `services/quant-api/app/market_data/newow/product_reader.py`、`product_service.py`、`source_facts.py`；
`packages/quant-core/guiyi_quant/newow/product_adapters.py`、`product_contracts.py`、`reference_trades.py` 及实际版本定义。
测试：`test_product_reader.py`、`test_product_adapters.py`、`test_reference_interruptions.py`、
`test_reference_trades.py`、`test_product_service.py`、`test_product_replay_invariants.py`、`test_product_source_facts.py`。
合同：openspec/specs/newow-product-reference-trading/spec.md。

**接口职责：** reader 将任务 1 的周中断映射为现有 `DataInterruption`，传入
`label_calculation_segments(identity, bars, data_interruptions)` 与 `replay_strategy`；ReferenceTradeProjector
消费保留标签的 replay。物理 owner/segment 与 calculation segment 保持独立。

- [ ] 添加 W1 同合约 owner 前缺价、owner 内缺价、外部合约缺价不污染、末尾缺价且无后继 Bar 的测试。
- [ ] 修正所有必要 D1-only 限定；不全局放开 60m，不只改某一分支条件。
- [ ] 中断 effective_at 使用已完成周端点；同周多缺价合并成一个稳定 identity，诊断保留原始日期。
- [ ] 验证恢复后状态只依赖新段有效周，预热不足不继承旧 Frame。多次中断、周线 NO_TRADE 暂停正确。
- [ ] 验证 CLOSED 保留、OPEN→DATA_INTERRUPTED、无 exit/已完成收益、跨断点 CLEAR 无法配对；
  初始 HOLD 不造 OPEN、初始无入场 CLEAR 继续保持已批准资格。
- [ ] 修正质量计数、source proof、cache/snapshot：不同 section 的重叠事实一致，历史宽窗不改变 warm-up owner。
- [ ] 保证 replay 最终返回带 calculation_segment_id 的输入，历史定位与统计使用同一身份。
- [ ] 明确 W1 专属版本/兼容边界，测试 D1 既有 Trade ID 与无关公式/profile 不因共享常量被无意改写。
- [ ] 验证当前 READY 与历史 PARTIAL 可以同时存在；末尾缺价或 warming 不能显示历史旧 READY。

最低行为断言（测试须在既有真实 replay fixture 上构造，不用手写预期输出冒充计算）：

```text
closed_before_gap remains CLOSED with unchanged ID and return
open_at_gap becomes DATA_INTERRUPTED; exit_marker/exit_price/reference_return are absent
clear_after_gap never references build_before_gap
replay(prefix) == prefix_of_replay(same_snapshot, extended_input) for causal outputs
read(chart_overlap) == read(reference_overlap) for Bar/quality identity and values
```

定向运行上述测试文件；再扩展 `services/quant-api/tests/newow` 中受影响 causality、snapshot、reference statistics 组。
结果不全绿先修复，不以“旧 W1 没开”豁免本次要开放的行为。

**出口：** W1 quality reader/core/reference 闭环通过；D1 语义和身份回归通过。

## 任务 3：候选能力与代表品种只读页面（P3）

**文件：** `product_release.py`、API `market_newow_product.py` schema、相关 capability route；
`apps/quant-web/src/api/newowProduct.ts`、`src/types/newowProduct.ts`、`src/pages/market/MarketDetailPage.vue`、
`src/components/market/detail/newow/` 和实际 Newow controller/view model。
测试：`test_candidate_preview.py`、`test_market_newow_product_api.py`、`test_product_socket_http.py`；
Web `newowCapabilities.test.ts`、`newowProductTypes.test.ts`、`useNewowProduct.test.ts`、
`newowReferencePanel.test.ts`、`MarketDetailPage.test.ts`；e2e `newow-product.spec.mjs`、`newow-chart-panes.spec.mjs`。

- [ ] 在隔离候选实现 D1/W1 chart/auxiliary/reference/comparator capability，更新实际 schema/parser；
  production Runtime/config 不改，60m/explanation 仍拒绝。测试各方向深链接与非法频率。
- [ ] 先跑新状态的 fixture/API/UI：READY、FLAT/无交易、WARMING、DATA_INTERRUPTED、PARTIAL、未完成周。
- [ ] 依据任务 0 选择 5–8 代表品种，读取固定 as_of 的同 snapshot chart/reference/auxiliary/comparator。
  数据不齐的场景显示真实阻断；不通过把错误文字放出来就宣称该品种业务完成。
- [ ] 使用空闲隔离 API/Web 端口，读取 code/as_of identity；自然首次打开、不刷新、不先访问相同页面预热。
- [ ] 验证实际图层、参考表、区段原因、BUILD/CLEAR 对应、历史定位、桌面/390px 移动显示。
- [ ] D1↔W1、三策略切换、快速切换取消、延迟旧响应、弹窗关闭再开都不会混入旧频率/旧品种结果。
- [ ] 将真实缺数留下供任务 4；代码/状态错误本阶段修复。避免并发压出 429 后循环刷新制造通过。

工程验证命令按当前 TESTING.md 的 Newow suite 和 Web package scripts 运行；截图更新前逐张检查差异，
不能放宽容差。真实页面和 fixture 结果分开记录。

**出口：** 代表路径的工程闭环正确，普通数据缺口有精确理由；能力只在隔离候选使用。

## 任务 4：原生审计、精确 prepare 与获批后恢复（P4）

**文件：** `historical_data_manager.py`、实际 `ContractWarmupPlanner` 定义、`rqdata_adapter.py`、
`storage.py`/Catalog publication；`newow/readiness.py`、`readiness_composition.py`；
`scripts/newow_weekly_recovery.py`、`newow_weekly_recovery_campaign.py`、`newow_recovery_partial_exception.py`、
`newow_weekly_source_verify.py`、`newow_weekly_acceptance.py`。
测试：`test_historical_data_manager.py`、`test_newow_readiness_cli.py`、`test_readiness.py`、
`test_weekly_recovery.py`、`test_weekly_recovery_campaign.py`、`test_recovery_partial_exception.py`、`test_weekly_acceptance.py`。

**依赖与顺序：** 本任务的 planner/恢复工程准备在任务 1/2 的共享覆盖接口稳定后即可连续编写，
不需要等生产授权；真正 apply 必须晚于代表验证、独立 Review 与精确批次授权。

- [ ] planner/readiness 复用任务 1 分类；同周已知缺价与未知缺日并存时仍暴露缺日，不能整周豁免。
- [ ] 同源 D1+W1 目标去重，跨月周包含两侧 D1 context；requested/effective through、lifecycle 和前缀完整保护。
- [ ] 严密区分正常缺口已归零与质量中断已解释；旧 W1 与 D1 冲突不进入普通缺数 apply。
- [ ] replan/读取质量证明使用同一 revisions；没有普通 target 不造零目标 apply receipt。
- [ ] 新总包/schema 如需扩展采用版本化 W1 profile；不从旧 D1/W1包删字段伪装兼容。
- [ ] 为有正常周且包含中断周的同月分区、全中断月、跨月D1提交后W1失败、短写/终态失败、未知提交、
  证据attempt/batch/unit错配、重复执行、来源身份错误添加隔离回归。
- [ ] 执行结果先可靠持久化，再独立读回；校验退出码、业务终态、报告可解析和实际写入事实，不依赖 stdout。
- [ ] 在当前任务代码上重做新原生审计与 prepare，固定 design 第 9 节所有数据批次字段；以当前需求窗口
  生成物理合约列表，旧 PT/SS/BZ/PG 等已完成窗口不因文档旧数字重做。
- [ ] 完成高风险独立 Review 和相关测试后，向 owner 提交一个具体可审的批次请求，说明真实请求/写入范围。
  无授权时停 apply；继续页面测试、文档、自审等独立工作，完整交付现有可集成工程。
- [ ] 收到范围明确批准后，仅执行获批部分一次；内部小批串行，逐单元保存来源/结果/读回/replan。
- [ ] 失败或结果不明按批准的异常/恢复边界处理；无重试授权不重试，不回滚成功分区或修改外部状态造绿。
- [ ] 批后独立只读核对完整分母与所有已处理单元，审计失败不抹去已知执行事实，但阻止完成结论。

验证组复用 TESTING.md “Newow 周线剩余工程收口”的命令集合，并追加任务 1 的质量分类用例。
partial exception 的旧工作树实现只有在当前基线仍缺必要修复且审查证明有价值时才按最小 diff 整合。

**出口：** 未授权时是可审精确数据批次与工程结果；获批执行后是可信结算与新的当前余额，二者不可混称。

## 任务 5：全 60 品种验收、D1 回归与 develop 集成（P5）

**文件：** 复用原生 readiness/acceptance、现有真实浏览器脚本；必要时扩展 `newow_weekly_acceptance.py`
及 `test_weekly_acceptance.py`，不复制行情/策略算法。更新产品 canonical、PROJECT_SOURCE.md、DECISIONS.md、
docs/ARCHITECTURE.md、TESTING.md 中实际变更的合同；STATUS.md 只记录真实已完成部分。

- [ ] 固定最终候选、source/quality版本、scope、as_of、实际 consumer 窗口，重跑 60×3 W1 API/策略矩阵。
- [ ] 每个组合证明 chart/reference 同 snapshot，辅助和比较器有独立正确状态；缩放/翻页不改统计口径。
- [ ] 180 个 W1 新页面首次加载，全量记录 code、as_of、product、strategy、frequency、预期/实际状态、
  chart/reference 可见性、错误与结果hash；抽查代表截图/交互。未知缺数即便有错误面板也不算业务完成。
- [ ] D1 180 组合按本轮固定 D1 截止回归；涉及共享 controller/来源证明时，保留 D1 自然首次加载全量证据。
- [ ] 保持原生 matrix 的 schema/分母：若它仍枚举 60m 180 个 UNOPENED 条目，完整保留，不能删掉凑矩阵。
  对外 W1 180、D1 180、未开放 60m 分开统计，不能写 W1 540/540 READY。
- [ ] 测试包含 prefix invariance、batch/restart parity、跨月/换主力、同 Bar转换、初始 CLEAR、质量段末尾、
  窗口交集证明；根据实际 diff 扩展 backend/module、Web unit/build、OpenSpec、Ruff/mypy、secret/diff检查。
- [ ] 独立 Review 按 Confirmed Issue、Risk / Needs Verification、Optional Improvement 分类，修复本版必要项。
- [ ] 核对最新 develop 依赖，在本任务 worktree 合并并处理实际语义冲突；重验受影响路径和 exact candidate。
  干净且范围正确时 commit/push、PR/记录、集成 develop，不覆盖主工作树其他暂存内容。
- [ ] 汇总每品种完成/未完成原因：普通缺口、完整正常历史、历史中断但当前恢复、仍 warming/中断、其他阻断。
  写明 full matrix 与局部补测的区别；不把本轮 partial evidence 外推为全量自然页面验收。

**出口：** CODE_COMPLETE、TEST_COMPLETE、REVIEW_COMPLETE、DEVELOP_INTEGRATED 与真实数据/页面验收分别结算；
仍有生产数据 Gate 时准确交付工程与 pending，不能提前标全部完成。

## 任务 6：发布候选与自然接续交接（P6，外部 Gate）

- [ ] 工程/业务证据齐备才形成精确 release candidate，列出对 D1/W1能力、版本、数据兼容及回退约束的影响。
- [ ] main/tag/Release 未授权就停相应动作；Runtime promotion 另列工作站、exact tag、服务和恢复边界，
  不由 release 批准隐含推导，也不提前修改生产配置。
- [ ] 获授权部署后，按正式合同确认下一次完整周生成、盘后维护、换主力后预热和用户页面自然读回。
- [ ] 自然事件未发生时保持待验，不手工重跑生产 weekly audit、不创建新自动化、通知或 Scope。
- [ ] 最终简报给出各层完成数、明确未完成名单/原因、实际验证与唯一最小下一步。

## 执行记录约定

执行会话更新本计划的复选框并在同一 evidence 根保存实际输出，避免另造多套设计/报告。
每次更新需保留 exact commit/cutoff 与 gate 边界；计划中的命令是验证入口，未运行不能勾选或填 passed。
仅因本会话上下文切换、技能建议逐步确认或出现可自主修复的测试失败，不得再次要求 owner 批准已认可的设计。
