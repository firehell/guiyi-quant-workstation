# Newow 策略与指标产品化 + 乐观参考交易 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现役苏冰、行情权威或执行权限的前提下，交付趋势/震荡/主升浪 × `1w/1d/60m` 九组合的指标、解释、主动作、过程提示、单品种参考交易和乐观统计。

**Architecture:** 保留模块化单体与 `MarketDataService` 唯一历史读入口，复用既有公式；新增多周期物理区段读取适配、typed Strategy Adapter 与纯计算 `ReferenceTradeProjector`。Newow 新查询在请求内共享事实后组织图表、参考历史和解释，Web 只消费结果；旧 D1 接口及 `view=trend` 保持兼容。不新增交易数据库、账户、订单、缓存服务、通知或 Runtime。

**Tech Stack:** 仓库锁定的 Python/FastAPI/SQLAlchemy、Quant Core、Canonical Parquet、Vue/TypeScript/lightweight-charts、pytest、Node test、Playwright、OpenSpec、Git/GitHub；不升级依赖、不新增第三方库。

**Spec:** `docs/tasks/2026-09-05-newow-product-reference-trading-design.md`

**规划日期 / 状态:** 2026-09-05；P4 Amendment 2026-09-06 / `OWNER_APPROVED_P4_AMENDMENT`。阶段事实仍只以 `STATUS.md` 为准。

**原计划历史基线:** `develop@4f4754ed6df67a1d828e35b82fe2269d7f020469`；文档分支 `docs/newow-product-reference-trading-v1@c7dc8fb41e5bd4cc3d2fa6ad4722e6a97eb96d86`。该段保留 Tasks 0–13 的历史身份。

**P4 Amendment 执行基线:** `origin/develop@c9d297b8318c1d4bdcfbfc1b4e2e46b55956e26c`，包含 PR #348/#349；任务分支 `feature/newow-product-reference-trading-p4`。Owner 本轮明确授权 P2/P3 收尾与 P4 后端实现、Review 和普通 develop 集成，不授权 P5/P6、生产或 release/Runtime 操作。

## Global Constraints

- 第一版只使用 `active_products.txt` 定义的研究品种和 completed Canonical `actual_dominant` 序列。
- 周期固定 `1w / 1d / 60m`；主策略固定 `trend / oscillation / main_rise`；九个组合独立，没有第十条综合交易策略。
- 主动作只有各策略自身 `BUILD / CLEAR`。J、D1–D3、D4–D6、4/7/11 等在本版属于 Hint；`quantity_effect=none`。
- 趋势主动作使用 B，震荡 BUILD/CLEAR 使用 Low/High，主升浪使用 MA45；绘图锚点不能替代语义价格。
- 参考政策 `newow_marker_reference_zero_cost_v1`；期货适配 `newow_futures_segment_interrupt_v1`；统计纳入 `entry_in_window_v1`。这些是归一新身份，不是牛哇私有公式身份。
- 有效主力区段内 BUILD 才能开始参考交易。warm-up BUILD 不补为有效建仓；同 Bar 震荡保留 CLEAR 后 BUILD；不从黄色状态直接推导已建仓。
- 未平仓换月为 `ROLLOVER_INTERRUPTED`，单列旧合约同周期最后 completed Close 的参考浮动；不伪造 CLEAR、不跨合约或跨频补价。样本末本身不是清仓。
- CLOSED 单笔 `(exit / entry - 1) * 100`，价格与收益使用 Decimal；汇总为简单相加的百分比点，不是账户累计收益。零 CLOSED 的胜率、均值与展示收益合计为 null/“—”。
- `display_window` 与 `performance_since / performance_through` 独立；改变 viewport 不改变统计。期初交易单列，不混入本窗口 CLOSED 统计。
- 每个周期独立读取，W1 允许零 Bar 的权威 owner 区段，60m 允许同 trading_day 多 Bar；同合约前缀完整分页，不借其他合约或截断后假称完整。
- 综合解释有明确 as-of，未来完成周线不能回填历史60m依据；各周期保留自己的时间和 physical contract。
- 照妖镜继续为 `repainting=true / formal_signal_eligible=false`；仅回看图层，不进入参考交易、当时可知 Hint 或收益。杯柄维持 D1 clean-room 与 confirmed_at 语义。
- 缺精确规则或可核对原件的功能标记 `EVIDENCE_REQUIRED`，阻塞该功能的完成声明；不得根据一般知识补公式、分数、分支、排序或六组合评分。
- 五窗口比较器 `10/20/24/30/52` 使用独立页面合同，其期末理论平仓不得进入 ReferenceTrade；不能自动修改主策略参数。
- 保留 `view=trend` 和 `/api/v1/market/newow/trend-detail` 原 D1 合同；HTDY、SuBing Event 深链与 Free 不回归。
- 不新增交易表、migration、持久缓存、Redis authority、scheduler、外部 LLM、选股、机会排序、账户或订单。
- `auto_order=false` 不变；现役 v1.9.15 与苏冰 Task11–13 状态只按真实证据更新，本计划不完成、触发或重启它们。
- 只进行任务范围内代码、测试和文档工作。生产 RQData/Canonical/PostgreSQL/Redis、Scope、通知、Runtime、main/tag/release 均不属于本计划执行权限；单独的只读真实数据验收也须明确环境和范围。
- 不读取、复制或提交凭据；完整第三方网页脚本、股票逐Bar及RQData原件不进入GitHub-safe资料；普通测试使用自有fixture和fake服务。

## 0. 执行组织、依赖与完成状态

P0–P6 是七个可独立审查的工作包，本文件是唯一实施顺序。每包从执行时最新 clean develop 创建独立 task branch/worktree；不要在正在跑苏冰的工作站 Runtime root 开发。独立审阅、允许集成后才合入 develop；本文件不自动授权 merge。共享文件只允许一个实现者写。

```text
P0 [Task 0–1]  → P1 [Task 2–5] → P2 [Task 6–8]
                       └─────→ P3 [Task 9–13]
                   P2 + P3已验证接口 → P4 [Task 14–16]
                                    → P5 [Task 17–20]
                                    → P6 [Task 21–22]
```

P3 缺证据项只阻塞自身；P4/P5 可以展示明确的 evidence-required section，但 P6 不能因此宣布完整交付。默认串行；P2/P3 只有独立文件、接口已冻结、测试环境互不影响时才允许并行只读审查，不并行修改核心模型/共享路由。

每个实现 Task 使用 fresh implementer，之后由独立 reviewer 检查 Spec compliance 与 quality；P1/P2/P3 的语义及每包最终整合需要 Standards/Spec 双轴结论。相同 exact head 的测试证据可以供 reviewer 使用，修复后须重跑覆盖测试；不能沿用旧 head 的最终批准。P1/P2 未关闭项不能仅“park”后宣称通过。

SDD 的 ledger/brief/report 只放本 Plan 专属、已忽略的临时工作目录，不成为第二个产品状态文件。不得因通用 skill 的清理步骤删除生产 root、他人 worktree 或原始证据。恢复执行时用 ledger + Git identity 核对，已完成且内容未变的任务不重做。

2026-09-05 当时本轮只编写 Plan，该记录仅解释 Tasks 0–13 历史。当前实施唯一入口是 Tasks 14–16；共同结束动作为定向 RED → 最小改动 → GREEN → 适用 lint/typecheck → 自审 → exact scoped commit → 独立 Review → 记录证据。

## 1. 文件与职责地图

路径以下均相对仓库根；“新增”表示本计划定义的新文件，不声称目前存在。

| 区域 | 现有入口 | 计划新增/改动 |
|---|---|---|
| P0 | PROJECT_SOURCE/DECISIONS/ARCHITECTURE/TESTING、现有详情Spec | 新增 `docs/tasks/2026-09-05-newow-product-reference-trading-coverage.md`、`openspec/specs/newow-product-reference-trading/spec.md` |
| Core契约 | `packages/quant-core/guiyi_quant/newow/` | 新增 `product_contracts.py`、`product_identity.py`、`product_adapters.py` |
| Core参考层 | 同上 | 新增 `reference_trades.py`、`reference_statistics.py` |
| Core解释 | 现有 subplots/cup/各primitive | 新增 `product_auxiliary.py`、`context_alignment.py`、`target_absorb_display.py`、`composite_explanation.py`、`page_comparator.py` |
| 应用读取 | `services/quant-api/app/market_data/actual_dominant_research.py`、`services/quant-api/app/market_data/newow/trend_detail_service.py` | 新增 `services/quant-api/app/market_data/newow/product_query.py`、同目录 `product_reader.py`、`product_service.py` |
| API | `services/quant-api/app/api/market_newow.py`、旧 schema | 新增 `services/quant-api/app/schemas/market_newow_product.py`；旧路由只做兼容回归，默认不迁移实现 |
| Web契约 | 现有 marketDetail/route/preferences | 新增 `src/types/newowProduct.ts`、`src/api/newowProduct.ts`、`src/utils/newowProductTypes.ts`、`src/utils/newowProductViewModel.ts`、`src/composables/useNewowProduct.ts` |
| Web页面 | `MarketDetailPage.vue`、`MarketDetailViewNav.vue`、Kline基础组件 | 新增 `components/market/detail/newow/` 下的 Workspace、ChartStage、ReferencePanel、ExplanationPanel |
| 测试 | pytest newow、工程检查、Node tests、Playwright | 各Task列出精确新增测试；现有因果回测/苏冰/退役测试不删除 |

不为参考展示重构整个 research_backtest。新适配器直接调用纯primitive；`NewowDailyBar` 可作为底层输入值对象，但新 envelope 必须显式带 frequency，不能让 D1 Engine 接收伪装成日线的60m。

## 2. 本计划冻结的接口选择

以下是 Spec 授权由 Implementation Plan 冻结的工程接口，不是牛哇原协议。

### 2.1 新HTTP面：一个品种查询、一个一致响应

新增 `GET /api/v1/market/newow/strategy-detail`，不新增CLI、POST或后台任务。

| 参数 | 合同 |
|---|---|
| product | 必填，小写 active 品种 |
| strategy | 必填，`trend / oscillation / main_rise` |
| frequency | 必填，`1w / 1d / 60m` |
| series_kind | 仅 `actual_dominant`，省略时取该值；contract参数不接受 |
| section | `chart / auxiliary / reference / explanation / comparator`；默认只计算`chart`，不接受`all` |
| from / through | `chart/auxiliary`可选且必须成对，ISO交易日窗口；from≤through |
| performance_since / performance_through | 仅`reference`，必须成对；省略时只读解析既有研究起点与最新可用完整交易日 |
| as_of | 可选、带时区时间；省略时冻结请求开始时间；不能晚于服务端now；筛掉所有晚于as_of的Bar/确认/换月事实 |
| chart_limit / chart_before | 仅`chart`；默认500、范围1–2000；cursor严格向左且绑定section输入世代 |
| component | 仅`auxiliary`且必填：`main_force_control / up_down_energy / zhaoyao_mirror / cup_handle` |
| history_limit / history_before | 仅`reference`；默认50、范围1–200；cursor绑定查询身份和reference输入指纹 |
| snapshot_token | 可选不透明进程内关联；不是权限凭证，失效或共同事实冲突返回409 |

响应是版本化 envelope：`meta / section / chart / auxiliary / reference / explanation / comparator`。五个section字段各自为`{delivery,status,value}` wrapper；请求项`delivery=delivered`并携带真实运行/证据状态，四个未请求项固定`delivery=not_requested,status=null,value=null`。`not_requested`不进入Core FeatureStatus。服务不得先计算整包再删除字段，section专属参数出现在其他section时返回422。

`meta` 至少返回schema版本、product/strategy/frequency/series、profile与公式集合、三个参考政策身份、requested/actual窗口、as_of、实际读取时间、来源/可用性、`data_revision_identity`（无可靠全局revision时为null）、section真实`input_content_sha256`与可空snapshot token。只有成功验证并实际缓存的结果签发token；超大bypass、缓存关闭、失败/不完整结果为null。reference另返回requested performance window、actual available through、`reference_cutoff`和viewport无关的`reference_input_sha256`；`ReferenceProjection.as_of == PerformanceWindow.cutoff`。

不同窗口整包hash不同是合法的。共同Bar需逐字段一致；参考分页只在相同reference指纹下拼接。数据更新引起指纹变化时清掉旧参考页并整体重取，而不是保留旧收益搭配新K线。

HTTP不接受evidence、signal、hash、contract、公式参数或客户端当前数值。非法参数422；身份/数据/token/cursor世代冲突409；重型并发或等待队列满429。未预期异常固定返回`500 {"detail":{"code":"NEWOW_INTERNAL_ERROR"}}`，测试注入含SQL/path/token/stack字样的异常并证明不回显。

时间比较统一转UTC instant：`fact_time <= reference_cutoff <= request_as_of`可见；严格晚于cutoff不可见。`as_of == server_now`合法，只有晚于now为422。若as_of早于所选through对应权威session完成时点，响应保留requested window并返回更早的actual available through/cutoff及降级availability。

P3服务端来源白名单：

| role | 允许source category | 构造来源/依赖 | mismatch |
|---|---|---|---|
| trend_weekly/daily | `strategy_replay` | 对应周期trend末端eligible frame；`BUILD→buy,HOLD→hold,CLEAR→sell,FLAT→wait`；`UNAVAILABLE`不构造fact | 缺失→unavailable；值/owner/version/time冲突→409 |
| trend_hourly | `strategy_replay` | 60m trend末端eligible frame；`BUILD/HOLD→holding,CLEAR→cleared,FLAT→idle`；`UNAVAILABLE`不构造fact | 同上 |
| oscillation_weekly/daily/hourly | `strategy_replay` | 对应周期oscillation末端eligible frame；`BUILD/HOLD→holding,CLEAR→cleared,FLAT→idle`；`UNAVAILABLE`不构造fact | 同上；不得用所选主策略替代 |
| volatility_daily_prefix | `canonical_bar_prefix` | D1同owner最多21根completed Bar及source identities | 短前缀→warming；owner/time/value冲突→409 |
| signal_daily/signal_weekly | `strategy_replay` | 按上述trend映射构造PageSignalFact | 末端不可用则target/absorb unavailable |
| cross_weekly_buy | 当前无获准来源 | 不从Action或颜色推断 | evidence_required |
| target_daily/target_weekly/target/high | 当前无已证明命名main-value映射 | 不构造PagePriceFact | 逐role evidence_required |
| cost_daily/cost_weekly/cost | 当前无已证明命名main-value映射 | 不构造PagePriceFact | 逐role evidence_required |
| current_price | `canonical_bar_close` | view slot最后completed close，值必须等于权威Bar.close | 不等→409 |
| previous_close | 当前无获准来源 | 不构造，guard_active=false并保留raw/display | evidence_required；不得用上一根当前周期Close |
| frozen rule hashes | `frozen_source_identity` | 仅证明page/AI/optimizer规则来源版本 | 不能证明当前值；不一致→evidence_required |

每项source fact输出role/source category/formula或adapter version/frequency/bar_end/physical contract/segment/as_of/dependency fingerprint。unknown role/source、missing value、owner/version/as_of不一致均有独立负测。

### 2.2 Core与应用的公有符号

| 文件 | 本计划新增符号及合同 |
|---|---|
| product_contracts.py | `ProductIdentity`、`ProductBar`、`OwnerBoundary`、`StrategyAction`、`StrategyHint`、`StrategyFrame`、`StrategyReplay`、`FeatureStatus` |
| product_identity.py | `build_signal_id(identity, contract, segment_id, bar_end, action, sequence) -> str`；`build_reference_trade_id(entry) -> str` |
| product_adapters.py | `replay_strategy(identity, bars) -> StrategyReplay`；bars含显式eligible前缀；输出只包含有效主动作/提示 |
| reference_trades.py | `ReferenceTrade`、`ReferenceProjection`、`ReferenceTradeProjector.project(replay, boundaries, as_of) -> ReferenceProjection` |
| reference_statistics.py | `PerformanceWindow`、`ReferenceSummary`、`summarize_reference(projection, window) -> ReferenceSummary`；`reference_return_pct(entry, exit) -> Decimal` |
| product_reader.py | `NewowProductReader.load(query, as_of) -> ProductReadSet`；只依赖MarketDataService/已存在coverage事实 |
| product_auxiliary.py | `calculate_product_auxiliary(identity, bars) -> AuxiliaryResult`；杯柄D1，照妖镜独立retrospective |
| context_alignment.py | `align_completed_context(frames_by_frequency, as_of) -> ContextSnapshot` |
| target_absorb_display.py | `calculate_target_absorb(context, evidence) -> FeatureResult`；证据不满足时不返回推测值 |
| composite_explanation.py | `calculate_composite_explanation(context, evidence) -> FeatureResult`；包含规则/评分/16组合/first-action token |
| page_comparator.py | `compare_page_windows(identity, bars, evidence) -> FeatureResult`；不能调用ReferenceTradeProjector修改其状态 |
| product_service.py | `NewowProductService.query(query) -> NewowProductResult`；合并上述事实，不计算新的信号 |

`FeatureStatus` 的运行状态与证据状态独立：运行 `ready / warming / unavailable / not_applicable / evidence_required`；证据 `ACTIVE_CODE_VERIFIED / RESEARCH_EVIDENCE_ONLY / EVIDENCE_REQUIRED / OUT_OF_SCOPE`。非ready结果带reason且不能用0冒充数值；这些枚举不替代页面stale状态。

### 2.3 跨任务对象字段约定

`StrategyReplay` 固定包含 `identity / frames / actions / hints / diagnostics`；`main_values` 是供包装一致性比较的只读投影：每根Bar的 `bar_end / main_state / band-or-channel values / ordered main actions`，不包含测试自行重算的公式。`StrategyFrame`包含ProductBar、主状态、主图值、该Bar的主动作/Hint及可用性。Task4的原primitive测试oracle将原输出映射到同一投影；不能调用待测adapter产生oracle。

`OwnerBoundary`包含product、旧/新contract、旧/新区段身份、权威生效trading_day及对应session边界时间、来源；没有权威证明的边界不构造。`ProductReadSet`包含按周期分组的完整replay输入、各段owner、截止时点内的边界、resolved display/performance窗口、每项上下文来源；`replay_bars`属性指当前所选策略频率的完整读取输入，用于4001根分页断言。

`ReferenceProjection`包含 `trades / bar_level_hints / unassigned_hints / diagnostics / as_of`。`ReferenceSummary`包含窗口及纳入政策、CLOSED胜/负/平计数、win_rate_pct、mean_return_pct、sum_return_percentage_points、OPEN/中断/期初计数及对应记录集合；缺有效闭合交易时三个比率为null。

`FeatureResult`包含status、evidence_status、reason_code、formula_versions、source_bars、value；value按功能分为typed目标价、综合解释或比较结果，API不接受任意对象。`evidence`为P0逐项核对后登记的规则/原件hash与适用identity，不是只写true就跳过验收的布尔开关；None表示没有核对证据。P3可在证据补齐后细化对应typed value字段，但不得改变主策略/参考交易接口或用没有证据的字段冒充完整原规则。

测试工厂只用自有数据。Task3新增paged_reader；Task4新增primitive_input及直接原primitive oracle；Task10新增multiperiod_context；Task11/12新增context及证据缺失用例；Task13的verified_comparator_contract仅在证据核对后建立；Task14新增same_performance_different_viewports；Task15/16在同目录conftest注册product_api_client、forbidden_writes；Task18在测试内定义createProductResourceHarness；Task19/20在测试内定义typed UI fixture；Task21在helper定义installNewowProductFixtures。每项都是计划新增，不是假设已存在的函数。

### 2.4 标识和数值

ProductIdentity含product、strategy、frequency、series_kind、profile_id、formula_versions。新产品profile统一命名 `newow_product_{strategy}_{frequency}_v1`；仅表示装配范围，保留底层公式版本。旧D1响应继续使用旧profile/marker/calculation身份。

ProductBar包装既有NewowDailyBar并显式带frequency/series_kind；每根bar必须completed。segment_id基于真实owner区段起点与合约，不含查询截止、当前可变区段末尾或本次输入hash；同一合约退出后重回rank1得到新的区段身份。

StrategyAction含signal_id、identity、physical_contract、segment_id、bar_end、trading_day、sequence、kind、reference_price、anchor_price、related_build_id、原内核source_marker_id/关联及trade_eligibility。Hint含独立ID、上述来源、kind、known_at、anchor_price、`quantity_effect=none`与retrospective标志。无可靠同Bar顺序的Hint为Bar级记录，不强行归属交易。

`ReferenceTrade`字段完全覆盖Spec§9；ID由有效entry动作和参考政策生成，不含后续exit、收益、viewport或当前数据hash。相同ID在同一输入世代内内容冲突报错；合法数据修订生成新读世代，允许重算，不称不可变Event。

Decimal计算使用局部precision=28、ROUND_HALF_EVEN，不改全局decimal上下文；不先按显示位数舍入。价格非法/非有限/≤0必须拒绝。数值串传给Web；图表可转换为有限number用于坐标，但Web不得重新做收益运算。

## 3. 统一验证与提交约定

后端定向命令形式：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q -m "not isolated_postgresql and not manual_acceptance" services/quant-api/tests/newow
```

Web测试使用仓库已有Node test，不改成其他框架：

```bash
pnpm -C apps/quant-web exec node --test tests/newowProductTypes.test.ts
```

每Task下的测试命令先在新增测试后运行并记录预期失败，再在最小实现后运行通过。自测后用 `git diff --check`；只stage本Task列出的文件，不使用 `git add .`。每包结束按TESTING.md扩展验证并进行独立Review。纯证据/文档Task不伪造TDD失败，只做引用、结构、OpenSpec、secret/diff校验。

所有命令均在隔离开发worktree执行；测试依赖fake或临时数据，不启动真实RQData、production DB/Redis或launchd。下面的Expected均是验收目标，不是本轮执行结果。

---

## Task 0: P0 — 审批基线与证据可用性清单

**Files:**
- Read: `AGENTS.md`、`STATUS.md`、`docs/DEVELOPMENT.md`、本Spec/Plan、`docs/research/newow-v3.2.82/README.md`、`REPLICATION_MANUAL.md`、`evidence/source-registry.json`、`evidence/full-local-evidence-manifest.json`。
- Create: `docs/tasks/2026-09-05-newow-product-reference-trading-coverage.md`。
- Modify metadata only: `docs/tasks/2026-09-05-newow-product-reference-trading-design.md`。

**Interfaces / 依赖:** 整体Design批准 → 逐功能来源清单与可实施/证据阻塞结论；不修改公式。

- [ ] **读回基线和范围：** fresh读取develop、docs分支、worktree和dirty state；若两份文件尚未进入develop，只走独立docs PR，不直接合入。

```bash
git fetch origin develop docs/newow-product-reference-trading-v1
git status --short --branch
git worktree list --porcelain
git log -5 --oneline origin/develop
git diff --name-status origin/develop...origin/docs/newow-product-reference-trading-v1
```

- [ ] **建立coverage表：** 每项写 `feature / applicable strategy-frequency / formula_version / retained source / test / local evidence manifest entry / evidence status / blocker`；覆盖三主策略、D/J/4-7-11、三副图、杯柄、目标选择、13格、确定性/方向/ATR/first-action、16组合、五窗口。
- [ ] **只核对明确定位的原件：** 对已有manifest里的路径执行只读存在性和SHA-256比对；不得递归扫描用户目录、访问凭据或重新联网采集。如果只有摘要，记录具体缺失的规则/输入/排序证据为EVIDENCE_REQUIRED；不能把历史27/27算作这次测试。
- [ ] **同步审批元数据：** Design标为Owner已批准用于实施规划，保留原文和历史基线；Plan仍待实施审阅。原报告中的历史完成度不覆盖当前代码事实。
- [ ] **验证与交付：** 引用路径存在、统计不伪造、原件不重新分发；运行 `python3 scripts/engineering/secret_scan.py --json` 和 `git diff --check`，提交 `docs(newow): map approved scope and evidence gates`。缺失P3证据不阻塞P1/P2，但记录哪些P3任务不能宣称完成。

---

## Task 1: P0 — 将只读参考产品边界写入规范

**Files:**
- Modify: `PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`。
- Modify: `docs/tasks/2026-09-03-market-detail-v1-remaining-design.md` 中被本Spec替代的Newow条款，保留HTDY/SuBing/Free合同。
- Create: `openspec/specs/newow-product-reference-trading/spec.md`。
- Read/Test: `tests/engineering/test_canonical_consistency.py`、`tests/engineering/test_repository_hygiene.py`。

**Interfaces / 依赖:** Task0 → accepted Newow产品合同；先过规范Review，再改语义代码。

- [ ] **写明确条款：** 允许Newow只读建仓/持有/清仓状态、ReferenceTrade和乐观摘要；这些是新增产品能力，不是恢复已退役账户/策略事件域。保留原D1公开入口。
- [ ] **把Spec的10个Requirement与12个Scenario原义纳入新OpenSpec：** 使用 `## Purpose / ## Requirements / ### Requirement: / #### Scenario:`；每个Requirement含SHALL/MUST。禁止把缺证据、无主动作、会重绘三种情况合并成“无信号”。
- [ ] **冲突清理：** 旧“固定Trend日线”只约束兼容入口，不再约束新view=newow；旧“禁止全历史策略效果”改为禁止模糊账户收益，新参考统计是明确例外。不要放松AGENTS的数据/未来函数/真实订单规则。
- [ ] **规范审阅：** 校验文档没有写Newow已发布或苏冰已完成；不为了规范更新重写STATUS中的生产事实。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py tests/engineering/test_repository_hygiene.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: 真正通过后记录规范可实施；测试若仍硬编码“禁止任何Newow参考展示”，仅按新Spec精确调整相应断言，保留账户/订单/退役保护。提交 `docs(newow): accept read-only product and reference contracts`，P0独立双轴Review通过后才进入P1。

---

## Task 2: P1 — 统一值对象、稳定身份与自有测试工厂

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/product_contracts.py`、`product_identity.py`。
- Create: `services/quant-api/tests/newow/product_fixtures.py`、`test_product_contracts.py`；Modify: 同目录 `conftest.py`。

**Interfaces / 依赖:** Task1 → 本计划§2.2–2.4的不可变契约及`product_cases` pytest fixture。

- [ ] **先写契约测试：** 使用真实dataclass，拒绝unknown strategy、15m产品频率、未完成Bar、naive时间、非Decimal/NaN/非正参考价、同ID冲突。示例：

```python
def test_signal_identity_does_not_depend_on_viewport(product_cases):
    case = product_cases.closed()
    assert case.entry.signal_id == product_cases.closed().entry.signal_id
    assert case.entry.signal_id != product_cases.closed(frequency="60m").entry.signal_id
    assert case.entry.signal_id != product_cases.closed(strategy="main_rise").entry.signal_id
```

- [ ] **实现契约与ID：** frozen dataclass、显式枚举校验；ID对身份字段的canonical JSON计算SHA-256。新ID不能包含窗口末尾或会变化的收益，旧marker ID保留为来源，不改旧API语义。

```python
payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
identity = hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

`fields`严格为§2.4的身份元组：product、strategy、frequency、公式集合、contract、真实segment起点、UTC bar_end、action、sequence；不是任意对象序列化。
- [ ] **测试工厂合同：** `product_cases`是本目录conftest注册的factory实例；固定UTC `as_of` 为2026-01-09T16:00:00Z，所有交易fixture的Bar均早于该时间；`closed(strategy="trend", frequency="1d", entry="100", exit="110")`返回含identity、bars、replay、entry、exit、boundaries、as_of、window的真实类型case。自有两Bar为2026-01-05/06，RB2605，同段，BUILD序号0/CLEAR序号0；60m变体为同日两个不同bar_end。价格用Decimal，OHLC取包含reference的合法正数。`open()`、`interrupted(mark="90")`、`same_bar_rebuild()`、`warmup_only_build()`构造对应显式动作；不得通过业务公式产生预期值。
- [ ] **扩展真实实例覆盖：** identity跨窗口稳定、同合约不同owner段不同、重复事件可比较、hint无quantity；各factory返回fresh对象，不能共享可变状态。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_product_contracts.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): add product contracts and stable identities`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 3: P1 — 三周期读取、完整前缀与权威换月边界

**Files:**
- Create: `services/quant-api/app/market_data/newow/product_query.py`、`product_reader.py`。
- Create: `services/quant-api/tests/newow/test_product_reader.py`。
- Reuse/read: `app/market_data/actual_dominant_research.py`、`market_data_service.py`、`coverage_source.py`、`domain.py`。

**Interfaces / 依赖:** Task2 → NewowProductQuery、ProductReadSet；供策略与服务使用，不产生信号。

- [ ] **Fake-MarketDataService测试先行：** 构造4001根60m同合约前缀，2000/2000/1分页；W1区段A有Bar、区段B零Bar、区段C有Bar；同日多60m；原MDS抛missing/owner错误必须原样分类失败。沿用现有 `_FakeMarketData.query_page` 形状而非读取本机Parquet。

```python
def test_reader_consumes_all_prefix_pages(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=4001, page_size=2000)
    result = reader.load(query, product_cases.as_of)
    assert len(result.replay_bars) == 4001
    assert len(fake.physical_page_requests) == 3
    assert all(r.contract == "RB2605" for r in fake.physical_page_requests)
```

Task内在测试工厂新增 `paged_reader`，返回真实reader、query、可记录调用的fake；精确测试输入数量如上。
- [ ] **查询校验：** 用§2.1合同；读取真实owner段起点，不以performance_since冒充段起点；默认performance窗口只读解析coverage既有起点及完整可用日并返回。缺口、lifecyle元数据缺失直接失败，不运行warm-up修复。
- [ ] **MDS分页：** `SeriesPageQuery(... before=最后允许时间+1微秒, limit=2000)`；读取后下一页before使用本页最早bar_end，严格递减直到has_more_before=false。空页但has_more、cursor不前进、重复冲突立即失败；没有“只保留最后2000根”。
- [ ] **区段与as-of：** MDS权威owner分段、Calendar/Session共同确定边界。只有截止as_of已生效的下一owner才能证明中断；请求截断的end不代表真实换月。若当前查询窗口末尾看不到下一根W1，仍可由截止as_of内的映射边界中断旧持有；禁止读取as_of之后已知映射再回填。
- [ ] **输入一致性：** actual与physical共同Bar逐时间/OHLCV/OI核对；bar_end严格递增、trading_day非递减；W1零Bar段保留边界但不生成Bar。请求内按contract/frequency/cutoff复用读结果，取消时在分页边界退出，不能开启常驻cache。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_product_reader.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): read complete multi-period owner segments`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 4: P1 — 三策略适配与有效动作引用

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/product_adapters.py`。
- Create: `services/quant-api/tests/newow/test_product_adapters.py`。
- Reuse: `trend_band.py`、`escape_d123.py`、`oscillation_channel.py`、`main_rise.py`、`magic11.py`；不重写公式。

**Interfaces / 依赖:** Task2/3 → `replay_strategy(identity, bars) -> StrategyReplay`，供P2/P3共享。

- [ ] **逐值包装测试：** 九组合逐prefix调用新adapter与原primitive，比较主状态/动作数量/时间/参考价和适用hint。不同frequency不得继承状态。

```python
@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_adapter_preserves_primitive_values(product_cases, strategy, frequency):
    case = product_cases.primitive_input(strategy, frequency)
    actual = replay_strategy(case.identity, case.bars)
    assert actual.main_values == case.run_original_primitive().main_values
```

Task内新增 `primitive_input`：固定自有OHLC序列，直接调现有三个step函数作为包装一致性oracle；它不替代本地原件的page-parity重放。
- [ ] **装配：** 对每个owner段初始化新内核，逐根喂同合约合法前缀。趋势使用page-v2 primitive，不用D1 Engine强行接受60m。主升浪保持MAIN_RISE_PAGE_V1公式集合；只包装已有动作与hint，不把辅助信号用于主状态过滤。
- [ ] **引用：** 趋势校验原related_marker_ids；规范ID与source ID映射后保留明确related_build_id。震荡/主升浪没有原关联时，在同段有效输出上建立确定配对引用。有效主力之前的BUILD只seed公式；只有适配器保留的同段prewarm witness明确证明其来源时，之后的孤立CLEAR才能标为 `NO_ELIGIBLE_ENTRY`。没有该证明的裸CLEAR、真正丢失或跨域引用一律 `PAIRING_CONFLICT`，不能用此分类吞掉损坏。
- [ ] **同Bar顺序与持有分离：** 原oscillation signals顺序原样保留；HOLD可与“无本段参考建仓”并存，不能制造entry。语义参考价按B/Low-High/MA45；所有hint的quantity_effect为none。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_product_adapters.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): adapt three strategies without changing formulas`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 5: P1 — 跨频、恢复与原公式回归闸门

**Files:**
- Create: `services/quant-api/tests/newow/test_product_replay_invariants.py`。
- Test: 现有 `test_trend_band_page_v2.py`、`test_oscillation_channel.py`、`test_main_rise_page_v1.py`、`test_trend_detail_service.py`、`test_research_backtest.py`、`test_research_walk_forward.py`。

**Interfaces / 依赖:** Task3/4 → P1接口冻结证据；不扩展因果收益模型。

- [ ] **不变量测试：** 对每个非重绘组合，任意前缀重放输出等于整段同前缀；batch等于逐Bar增量；丢弃内存后从同前缀重建结果一致；合约切换和同合约第二owner段无状态串联。

```python
def test_prefix_invariance(product_cases):
    case = product_cases.primitive_input("trend", "60m")
    full = replay_strategy(case.identity, case.bars)
    for end in range(2, len(case.bars) + 1):
        prefix = replay_strategy(case.identity, case.bars[:end])
        assert prefix.frames == full.frames[:end]
```

- [ ] **真实反例形状：** 用自有fixture表达SC2302零周Bar与SC2303周owner，不复制原始行情；验证60m同日不触发D1严格交易日递增错误、warm-up只同合约且完整。新增具体fixture断言，不以fixture通过声称真实SC数据已重新复算。
- [ ] **完整P1验证：** 跑newow整个目录及原actual-dominant loader测试，确认既有research成本/next-open/limit和旧D1测试不变。失败回对应Task修复；不得通过删测试冻结错误输出。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow services/quant-api/tests/data_foundation/test_actual_dominant_research.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `test(newow): freeze product replay and owner invariants`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 6: P2 — 纯参考交易配对内核

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/reference_trades.py`。
- Create: `services/quant-api/tests/newow/test_reference_trades.py`。

**Interfaces / 依赖:** Task2/4 → ReferenceTrade、ReferenceProjection、ReferenceTradeProjector；纯函数，无IO。

- [ ] **先测试BUILD/CLEAR：** 有效BUILD生成OPEN，有关联CLEAR生成CLOSED；无有效entry的正常前缀孤立CLEAR只作诊断，引用冲突失败；同ID同内容幂等、异内容失败；同Bar先CLEAR再BUILD。

```python
def test_pairing_and_rebuild(product_cases):
    case = product_cases.same_bar_rebuild()
    result = ReferenceTradeProjector().project(case.replay, case.boundaries, case.as_of)
    assert [t.status for t in result.trades] == ["CLOSED", "OPEN"]
    assert result.trades[0].exit_signal_id != result.trades[1].entry_signal_id
    assert result.trades[0].exit_bar_end == result.trades[1].entry_bar_end
```

- [ ] **实现唯一状态流：** 校验输入顺序而非无条件sort掩盖乱序；按(bar_end, sequence)消费主动作。维持每一identity/segment最多一笔有效OPEN；重复BUILD不是加仓，报PAIRING_CONFLICT。只校验本世代规范引用，不根据收益反推配对。
- [ ] **生成记录：** 覆盖Spec§9所有字段，status与字段一致；CLOSED有exit与return，OPEN无exit/已实现return；holding_bars为两动作间本周期有效Bar间隔数量，不按自然日差推算。trade_id以entry为基础，关闭不改ID。
- [ ] **异常拒绝：** 跨策略/周期/合约/区段关联、非finite价格、裸Hint输入均拒绝。trade_eligibility=NO_ELIGIBLE_ENTRY不生成虚构交易，诊断仍可展示。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_reference_trades.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): project explicit build-clear reference trades`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 7: P2 — 换月中断、参考浮动与提示归属

**Files:**
- Modify: `packages/quant-core/guiyi_quant/newow/reference_trades.py`。
- Create: `services/quant-api/tests/newow/test_reference_interruptions.py`。

**Interfaces / 依赖:** Task3/6 → 完整OPEN/CLOSED/ROLLOVER_INTERRUPTED及hint关联。

- [ ] **测试负浮动不消失：** entry=100、中断close=90；保留-10%mark_change，exit和realized return为null；W1最后估值可早于映射中断日。

```python
def test_interruption_is_not_a_clear(product_cases):
    case = product_cases.interrupted(mark="90")
    result = ReferenceTradeProjector().project(case.replay, case.boundaries, case.as_of)
    trade = result.trades[0]
    assert trade.status == "ROLLOVER_INTERRUPTED"
    assert trade.mark_change_pct == Decimal("-10")
    assert trade.exit_signal_id is None
    assert trade.reference_return_pct is None
```

- [ ] **边界处理：** 只消费已生效OwnerBoundary；用旧有效段同周期最后completed Close估值，不能取physical前缀末尾的区段外Bar。缺价保留记录、mark字段null+原因；查询截止不能制造boundary。
- [ ] **样本末/as-of：** 同一数据prefix更早截止时OPEN，真实CLEAR到来后才CLOSED；截断到换月前不提前中断。旧合约后续非rank1行情不能估值已中断记录。
- [ ] **Hint关联：** 非重绘、known_at不晚于as_of且能确定处在该交易内的hint挂接hint_ids；空仓提示保留总历史；主动作同Bar但顺序不明确的hint只作为Bar级提示。J/D不改变任何entry/exit/收益字段；照妖镜在输入边界拒绝。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_reference_interruptions.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): retain interrupted trades and explanatory hints`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 8: P2 — 统计窗口、Decimal与空样本

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/reference_statistics.py`。
- Create: `services/quant-api/tests/newow/test_reference_statistics.py`。

**Interfaces / 依赖:** Task6/7 → PerformanceWindow/ReferenceSummary与entry_in_window_v1；P4使用。

- [ ] **独立数值测试：** 两笔+10%/-10%合计0个百分点而非复利-1%；只有一笔CLOSED为-10%则胜率0、均值-10；无CLOSED则三个比率字段都null。所有期初/OPEN/中断数量独立可查。

```python
def test_decimal_return_is_not_compounding():
    assert reference_return_pct(Decimal("100"), Decimal("110")) == Decimal("10")
    assert reference_return_pct(Decimal("100"), Decimal("90")) == Decimal("-10")

def test_no_closed_trade_has_no_performance_number(product_cases):
    case = product_cases.open()
    projection = ReferenceTradeProjector().project(case.replay, case.boundaries, case.as_of)
    summary = summarize_reference(projection, case.window)
    assert summary.closed_count == 0
    assert summary.win_rate_pct is None
    assert summary.mean_return_pct is None
    assert summary.sum_return_percentage_points is None
```

- [ ] **核心算术：** 使用局部precision=28/ROUND_HALF_EVEN后计算，原值保留十进制串，不按UI小数位round后再合计。

```python
with localcontext() as ctx:
    ctx.prec = 28
    ctx.rounding = ROUND_HALF_EVEN
    value = (exit_price / entry_price - Decimal("1")) * Decimal("100")
```

- [ ] **样本成员：** entry trading_day在统计窗口内、exit在截止/as-of内才属于CLOSED统计；期初存在entry的记录独立initial集合，不混入窗口交易胜率。窗口内交易的状态在该窗口截止快照计算，不能先用后来CLEAR关闭后再裁剪。
- [ ] **界面独立性测试：** 同performance及reference输入、更改display from/through，summary与trade_id相同；缩放不强平。禁止跨九组合/60品种合计为账户，禁止年化、资金回撤、净值字段。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_reference_statistics.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): add explicit closed-reference statistics`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 9: P3 — 三个副图与日线杯柄

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/product_auxiliary.py`。
- Create: `services/quant-api/tests/newow/test_product_auxiliary.py`。
- Reuse: `subplots.py`、`cup_handle.py`、`profile.py`、`magic11.py`；不改公式。

**Interfaces / 依赖:** P0证据等级/P1数据 → AuxiliaryResult与分图能力矩阵。

- [ ] **原输出包装测试：** 三副图在每个同物理段与原函数逐值对齐；短前缀遵守各函数warming，不统一加120根Gate。杯柄仅1d。

```python
def test_cup_and_repainting_boundaries(product_cases):
    case = product_cases.primitive_input("trend", "60m")
    result = calculate_product_auxiliary(case.identity, case.bars)
    assert result.cup_handle.status == "not_applicable"
    assert result.mirror.repainting is True
    assert result.mirror.formal_signal_eligible is False
```

- [ ] **分组：** retrospective_layers单独存照妖镜；不把其回填点放hints或Trade。杯柄D1使用既有clean-room profile，pivot_at和confirmed_at都保留，只有confirmed_at<=as_of的解释可用。
- [ ] **提示适用性：** 原mainrise已输出D1–D6/J/4-7-11不重复计算第二份；趋势和震荡可显示共享辅助图，但不得新增主动作。空仓hint不被交易列表过滤掉。
- [ ] **重绘隔离回归：** 增加未来Bar使镜子历史图改变，已有非重绘actions和ReferenceTrade不变；该测试不要错误要求镜子自身prefix-invariant。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_product_auxiliary.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): expose bounded auxiliary and retrospective layers`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 10: P3 — 多周期as-of对齐

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/context_alignment.py`。
- Create: `services/quant-api/tests/newow/test_context_alignment.py`。

**Interfaces / 依赖:** P1三周期frames → ContextSnapshot；供Task11/12使用。

- [ ] **时间测试：** 周五完成W1不得出现在周一60m context；当日D1尚未结束用之前完整D1；允许各周期正确owner不同，不能用当前60m合约替换历史周owner。

```python
def test_friday_weekly_bar_is_not_visible_on_monday(product_cases):
    case = product_cases.multiperiod_context()
    result = align_completed_context(case.frames_by_frequency, case.monday_as_of)
    assert result.weekly.bar_end <= case.monday_as_of
    assert result.weekly.bar_end != case.friday_weekly_bar_end
```

- [ ] **对齐算法：** 对每周期单独取最新completed且bar_end<=as_of的frame；确认型字段还须known_at/confirmed_at<=as_of。没有输入返回unavailable+缺失周期，不设neutral/0。
- [ ] **快照语义：** context给出每周期bar_end、source/contract/segment/formula与as_of；当前摘要不能写进历史交易原因。未实现历史解释则保留其明确不可用，不让前端借当前摘要补写。
- [ ] **可证范围：** 这是当前Canonical数据上的时间截止重算，不宣称拥有历史入库时刻或全局数据版本；缺PIT数据修订证据时不声称“当年数据库所见完全一致”。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_context_alignment.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): align completed multi-period context`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 11: P3 — 目标/吸筹通道与展示选择

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/target_absorb_display.py`。
- Create: `services/quant-api/tests/newow/test_target_absorb_display.py`。
- Update evidence rows only: `docs/tasks/2026-09-05-newow-product-reference-trading-coverage.md`。

**Interfaces / 依赖:** Task0证据Gate、Task9/10 → calculate_target_absorb；未知规则不猜。

- [ ] **证据先决：** 必须定位并核对 `newow_target_absorb_display_selection_page_v2` 的完整日/周选择、周线覆盖、昨收定义、clamp及warm-up规则。仅HHV/LLV10公式存在不等于展示选择已验证。
- [ ] **缺证据分支先测试：**

```python
def test_missing_selection_contract_is_not_zero(product_cases):
    result = calculate_target_absorb(product_cases.context, evidence=None)
    assert result.status == "evidence_required"
    assert result.value is None
```

- [ ] **证据满足后再实现：** 根据已核对规则在同周期/同合约通道值中选择，保留source_frequency/bar_end/contract、原始值与display值。已知HHV/LLV计算复用channel；不可仅凭摘要补选择分支。新增每一分支的自有输入/固定预期golden，覆盖周线覆盖与clamp边界。
- [ ] **停止条件：** 不完整时只交付准确状态壳并记录任务EVIDENCE_REQUIRED，不能标Task完整实现。P4可消费该结果，完整产品完成仍被阻塞。不得按通用交易知识猜缺失分支。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_target_absorb_display.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): expose evidence-gated target absorb display`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 12: P3 — 综合解释、评分与周日16组合

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/composite_explanation.py`。
- Create: `services/quant-api/tests/newow/test_composite_explanation.py`。
- Update evidence rows only: `docs/tasks/2026-09-05-newow-product-reference-trading-coverage.md`。

**Interfaces / 依赖:** Task0/10/11 → deterministic facts/token，绝不生成主动作/目标仓位。

- [ ] **分功能Gate：** 13格、方向、确定性四分项及caps、ATR20/Close与分档、first-action优先级、周日16组合各自有完整可核对规则。六组合评分/诊断映射若仅有摘要，继续EVIDENCE_REQUIRED，不推导。
- [ ] **先写防污染与证据测试：**

```python
def test_explanation_is_not_a_strategy(product_cases):
    result = calculate_composite_explanation(product_cases.context, evidence=None)
    assert result.status == "evidence_required"
    assert result.value is None
    assert not hasattr(result, "order")
```

- [ ] **有证据部分按原控制流落地：** 13格保留不可达warning分支现象，禁止顺手修正；16组合用核对后的确定表；输出规则ID、输入时间、参考仓位区间、direction、评分分项、volatility和first-action token。评分不是胜率；ATR不改BUILD/CLEAR；没有外部LLM调用。
- [ ] **边界golden：** 枚举输入状态证明warning原样不可达、同context确定性一致、缺一周期不伪造neutral、冲突/中性cap按原规则、参考仓位不能影响P2。未知部分各自partial展示准确状态，不能把已有一个矩阵当成全部解释完成。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_composite_explanation.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): restore evidence-backed composite explanations`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 13: P3 — 五窗口页面比较器独立封装

**Files:**
- Create: `packages/quant-core/guiyi_quant/newow/page_comparator.py`。
- Create: `services/quant-api/tests/newow/test_page_comparator.py`。
- Update evidence rows only: `docs/tasks/2026-09-05-newow-product-reference-trading-coverage.md`。

**Interfaces / 依赖:** Task0完整证据、P1 → compare_page_windows；不改变P2/因果研究。

- [ ] **确认完整合同：** 五窗口、信号构造、排序/并列规则、同Bar顺序、胜率/回撤定义均核对原件；不能只因已知同Close/零成本就猜排名算法。
- [ ] **独立性测试：**

```python
def test_comparator_terminal_valuation_does_not_close_reference(product_cases):
    case = product_cases.open()
    before = ReferenceTradeProjector().project(case.replay, case.boundaries, case.as_of)
    compare_page_windows(case.identity, case.bars, evidence=case.verified_comparator_contract)
    after = ReferenceTradeProjector().project(case.replay, case.boundaries, case.as_of)
    assert after == before
    assert after.trades[0].status == "OPEN"
```

`verified_comparator_contract`只在本Task证据核对和自有golden完成后提供；缺原件时此正向验收不得跳过后声称完成，只运行evidence-required拒绝分支。
- [ ] **实现独立结果：** 版本 `newow_hhv_llv_window_optimizer_page_v1` 仅用于确证算法；component明示样本内、不可执行。合约区段独立比较，不把多合约拼为证券单序列；期末理论平仓保留synthetic终值标志，不能输出StrategyAction/CLEAR。
- [ ] **期货汇总边界：** 本版按物理区段分别列窗口排名，不新增跨段账户排名；最新区段为默认展示但给出实际区间；该周期在最新段没有Bar时显示不适用/无可比较数据，不静默改为上一段。页面原始公式parity与这种期货区段适配分别标识。页面排名不能自动写参数，用户切策略/周期不修改原固定窗口默认值。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_page_comparator.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(newow): isolate in-sample page comparison semantics`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 14: P4 — 请求级应用编排与指纹

**Files:**
- Create: `services/quant-api/app/market_data/newow/product_service.py`。
- Create: `services/quant-api/app/market_data/newow/source_facts.py`、`snapshot_cache.py`、`resource_gate.py`。
- Create: `services/quant-api/tests/newow/test_product_service.py`。
- Create: `services/quant-api/tests/newow/test_product_source_facts.py`、`test_product_snapshot_cache.py`、`test_product_resource_gate.py`。
- Modify as needed within scope: `services/quant-api/app/market_data/newow/product_query.py`、`services/quant-api/app/market_data/newow/product_reader.py`。

**Interfaces / 依赖:** P1/P2/P3接口 → `NewowProductService.query(query) -> NewowProductResult`；通过P4 request wrapper扩展工程参数，不改变P2/P3公有函数签名。此前 Tasks 0–13 历史不重做。

- [ ] **先写串联RED：** 覆盖晚CLEAR/延长cutoff、夜盘trading_day、as_of早于窗口、晚换月、viewport/chart cursor/history_limit独立；默认chart对reference/auxiliary/explanation/comparator spy均零调用。

```python
def test_viewport_does_not_change_statistics(product_cases):
    service, chart_q1, chart_q2, reference_q = product_cases.same_performance_different_viewports()
    first_chart = service.query(chart_q1)
    a = service.query(reference_q.with_snapshot(first_chart.meta.snapshot_token))
    second_chart = service.query(chart_q2)
    b = service.query(reference_q.with_snapshot(second_chart.meta.snapshot_token))
    assert a.reference.value.summary == b.reference.value.summary
    assert a.meta.reference_input_sha256 == b.meta.reference_input_sha256
```

- [ ] **窗口解析：** 增加应用层resolver，使用MDS Calendar/Session和trading_day解析requested/effective performance through与reference cutoff；projection和summary使用同cutoff。非交易日、节假日、夜盘和未完成W1显式状态，不用午夜/now/任意Bar代替；定向测试覆盖`fact_time == cutoff`、`cutoff == as_of`、Z与`+08:00`同instant、`as_of == now`合法以及未来一微秒422。
- [ ] **section编排：** chart只replay当前组合并先验证后裁剪；auxiliary只算一个component；reference读取完整统计输入；explanation只装配趋势/震荡三周期必要事实和D1前缀；comparator显式运行。chart读取不因默认performance扩大为研究全历史。
- [ ] **P3 source-facts builder：** 服务端构造role/source-category/formula-adapter/frequency/bar_end/owner/as_of/dependency绑定；当前数值逐字段来自受控replay/Bar。无法证明的target/composite输入精确降级，previous_close guard保持未激活。HTTP不接收evidence/signal/hash。
- [ ] **一致性和分页：** section指纹基于实际Bar/owner/Calendar-Session/确认事实/版本；reference指纹不含viewport/history limit。历史按`(entry_bar_end, entry_sequence, id)`稳定逆序；cursor只解析版本/查询身份/指纹/last-key并校验长度，不作为路径/SQL/对象反序列化入口。
- [ ] **Snapshot/cache：** 有界进程内token绑定共同依赖；entry key保存共同事实，section result/dedup key另含component、requested window、cursor/page identity和limit，不同专属参数绝不碰撞。LRU最多32条/128MiB/单条32MiB，超大bypass，关闭缓存结果等价；TTL仅淘汰；只有成功验证且缓存的结果返回token，超大/关闭/失败时为null。数据修订、旧cursor/token和共同事实冲突分类409。
- [ ] **取消/重型资源：** 分页和阶段边界检查取消；共享计算按消费者引用计数，最后消费者取消才停止。reference/comparator进程内并发1、等待2，队列满分类资源错误；阻塞计算不直接占满event loop，不跨线程共享Session。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_product_service.py
```

- [ ] **性能与正确性fixture：** 九组合、普通D1、长60m、4001分页、更大压力、多换月、W1零Bar、冷/热/修订、未请求零调用、取消/队列/cache淘汰/超大bypass。正式P95同一代表场景至少30次，冻结环境/HEAD/输入指纹/Bar与owner/窗口/cache状态并分解阶段。
- [ ] **提交与Review：** 只stage Task14源码/测试，提交 `feat(newow): compose sectioned product snapshots`；按影响验证后独立Spec/quality审阅。

---

## Task 15: P4 — typed只读API与序列化

**Files:**
- Create: `services/quant-api/app/schemas/market_newow_product.py`。
- Modify: `services/quant-api/app/api/market_newow.py`，只增加`/strategy-detail`处理器。
- Create: `services/quant-api/tests/newow/test_market_newow_product_api.py`。

**Interfaces / 依赖:** Task14 → §2.1新API，旧endpoint不扩参、不改变错误语义。

- [ ] **TestClient + dependency override：** fake service/get_db，不连接production。合法九组合/五section；非法section专属参数、strategy=mirror、frequency=15m、series=continuous、contract/evidence/signal/hash、naive/future as_of、坏游标422；`as_of==now`合法、未来一微秒422、Z与`+08:00`同instant；身份/数据世代409；资源满429。

```python
def test_reference_numbers_are_decimal_strings(product_api_client):
    response = product_api_client.get("/api/v1/market/newow/strategy-detail", params={
        "product": "rb", "strategy": "trend", "frequency": "1d",
        "section": "reference",
        "performance_since": "2026-01-05", "performance_through": "2026-01-06",
    })
    assert response.status_code == 200
    item = response.json()["reference"]["value"]["items"][0]
    assert isinstance(item["entry_reference_price"], str)
    assert isinstance(item["reference_return_pct"], str)
```

本Task的product_api_client fixture返回自有closed case；不能沿用真实DB session。
- [ ] **Schema：** 独立`market_newow_product.py`；status/strategy/frequency/section/delivery为Literal/enum，Decimal显式十进制string serializer、UTC ISO、清晰null；共同身份、section指纹、读取时间、组件source/evidence/applicability/repaint/formal eligibility/allowed uses/parity difference、分页与reference cutoff完整。禁止宽泛任意交易对象。
- [ ] **数据归属：** API只调用service并序列化，不计算收益、均线或拼动作。旧`trend-detail`继续原D1 schema/profile/marker/calculation；新路线禁止复用旧schema加一堆可选字段。
- [ ] **状态传递：** 没请求、warming、evidence required、not applicable、成功无动作、合法零CLOSED、输入冲突/失败分别表达。未请求section为null+not_requested，Core不新增该枚举；顶层ready不掩盖子功能缺口。杯柄clean-room来源与照妖镜retrospective语义完整。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_market_newow_product_api.py
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(api): add read-only Newow product detail`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 16: P4 — 旧D1兼容、无副作用与资源边界

**Files:**
- Create: `services/quant-api/tests/newow/test_product_readonly_compatibility.py`。
- Create: `services/quant-api/tests/newow/test_product_performance.py`。
- Test existing: `test_market_newow_api.py`、`test_trend_detail_service.py`、`test_research_backtest.py`。
- Conditional Modify (only Task 16.1 after measured significance): `packages/quant-core/guiyi_quant/newow/reference_trades.py`、`product_auxiliary.py`、以及其定向测试。

**Interfaces / 依赖:** Task14/15 → P4交付Gate；不通过替换旧API实现来省测试。

- [ ] **旧响应回归：** 现有D1 route、参数限制、profile和marker合同测试全部继续通过；view对应接口错误仍一致。新服务复用primitive不等于必须重写旧服务，薄适配只在全部旧合同可证明保留时才允许。
- [ ] **零副作用spy：** 依赖层RQData/network/通知/maintenance/DB commit/Redis写调用都注入“被调用即失败”的fake；一次新GET只走只读MDS路径。

```python
def test_new_get_does_not_mutate(product_api_client, forbidden_writes):
    response = product_api_client.get("/api/v1/market/newow/strategy-detail", params={
        "product": "rb", "strategy": "oscillation", "frequency": "60m",
        "from": "2026-01-05", "through": "2026-01-06",
    })
    assert response.status_code == 200
    assert forbidden_writes.calls == []
```

- [ ] **负载与只读合同：** fake行为证明无RQData、网络、通知、commit、Redis、Runtime；无60品种×九组合扇出；4001前缀与更大压力不截断；未请求reference/comparator零调用；旧cursor+新指纹409。
- [ ] **热点先测后改：** 测 `_attach_hints`、`_latest_owner_mark`、多auxiliary和P4重复读取/replay/serialize。只有占比或增长显著才按owner/有序区间建局部索引；用同BarCLEAR→BUILD、无序Hint、中断和Decimal逐字段差分证明等价，不建第二套投影。
- [ ] **性能报告：** 冷/验证后热/修订后重算各至少30次代表场景，记录排队/读取/校验/replay/projection/explanation-comparator/serialize/bytes/RSS。浏览器≤2s/500ms/300ms/100ms和完整统计≤5s仅保留P5/P6端到端目标，不冒充本轮实测。
- [ ] **Task 16.1 条件优化：** Task16主体只测量。若 `_attach_hints`/`_latest_owner_mark` 占比或增长显著，才在独立commit精确修改 `packages/quant-core/guiyi_quant/newow/reference_trades.py` 与 `services/quant-api/tests/newow/test_reference_trades.py`、`test_reference_interruptions.py`；若多auxiliary显著，才修改 `product_auxiliary.py` 与 `test_product_auxiliary.py`。逐字段差分通过后才能保留优化；否则记录无需优化，不改冻结Core。
- [ ] **P4 package Gate：** 在候选head逐条核对AC21–28；执行新P4测试、本轮实际修改的P2/P3保护测试、旧D1兼容、只读保护、相关Ruff/Mypy、OpenSpec/secret/diff和性能代表样本。已在相同相关tree通过且输入未变的证据可复用；不跑P5/P6或全仓库。
- [ ] **交付：** 只在实现与命令真实存在后更新TESTING.md。P4只读代码验收不等于P5 Web、完整page parity、OOS、发布或Runtime。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `test(api): protect legacy detail and read-only boundaries`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 17: P5 — 新Newow视角、路由与偏好兼容

**Files:**
- Modify: `apps/quant-web/src/types/marketDetail.ts`、`src/utils/marketDetailRoute.ts`、`src/utils/marketDetailPreferences.ts`、`src/utils/marketHomeRoutes.ts`。
- Modify: `src/components/market/detail/MarketDetailViewNav.vue`、`src/pages/market/MarketDetailPage.vue`。
- Create: `apps/quant-web/tests/newowProductRoutes.test.ts`。

**Interfaces / 依赖:** P4API → view=newow + strategy + 三周期；所有旧入口保持。

- [ ] **路由测试先行：**

```typescript
import assert from 'node:assert/strict'
import test from 'node:test'
import { parseMarketDetailRoute } from '../src/utils/marketDetailRoute.ts'
test('legacy Trend is still fixed D1', () => {
  assert.equal(parseMarketDetailRoute({symbol:'rb',view:'trend',frequency:'15m'}).kind,'invalid')
  assert.equal(parseMarketDetailRoute({symbol:'rb',view:'trend',frequency:'1d'}).kind,'valid')
})
test('Newow accepts the independent 60m workspace', () => {
  assert.equal(parseMarketDetailRoute({symbol:'rb',view:'newow',strategy:'oscillation',
    series_kind:'actual_dominant',frequency:'60m'}).kind,'valid')
})
```

- [ ] **单一控制器：** view=newow通过共享ViewNav选择strategy/frequency，不在workspace复制品种控制。普通新入口默认newow/trend/1d；旧view=trend仍D1，保留focus_bar_end和非法参数错误，不能把旧frequency=15m静默变成新view。
- [ ] **偏好：** 新增Newow偏好时升级现有schema到v2，读取v1/v9按原规则迁移HTDY/Free；Newow策略周期只能合法白名单，默认trend/1d；不得存contract、Event焦点或参考收益。旧URL仍可访问，无强制redirect丢参数。
- [ ] **回归：** 原Event identity函数输出不变；切view/product/strategy/frequency清旧选择和generation；首页仍三个bulk资源，不增加九组合预取。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
pnpm -C apps/quant-web exec node --test tests/newowProductRoutes.test.ts
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(web): add Newow view with legacy route compatibility`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 18: P5 — Web强类型、请求隔离与原子替换

**Files:**
- Create: `apps/quant-web/src/types/newowProduct.ts`、`src/api/newowProduct.ts`、`src/utils/newowProductTypes.ts`、`src/utils/newowProductViewModel.ts`、`src/composables/useNewowProduct.ts`。
- Create: `apps/quant-web/tests/newowProductTypes.test.ts`、`useNewowProduct.test.ts`。

**Interfaces / 依赖:** P4 envelope + Task17 identity → 可用、stale或错误的纯展示资源。

- [ ] **类型/竞态测试：** schema字段缺失、Decimal NaN/Infinity、错误contract/frequency/formula、旧请求晚回、同identity数据修订、不同窗口hash均测试。不能把hash改变一律判错；共同Bar冲突才错误。

```typescript
test('late response never replaces a different strategy', async () => {
  const harness = createProductResourceHarness()
  const oldRequest = harness.start('trend', '1d')
  const currentRequest = harness.start('oscillation', '60m')
  harness.resolve(currentRequest)
  harness.resolve(oldRequest)
  await harness.flush()
  assert.equal(harness.current().identity.strategy, 'oscillation')
})
```

本Task在test文件内实现无网络harness，使用可控promise和自有typed fixture；不靠sleep制造竞态。
- [ ] **前端验证：** product schema解析器逐字段校验值、顺序、identity与来源；先确认requested section是`delivery=delivered`且其他四项为`not_requested/status=null/value=null`，才可unwrap请求项的`value`。金额/收益保持字符串，只格式化，不把字符串转number再重新求和。图表坐标转换单独finite检查。
- [ ] **请求生命周期：** AbortController/现有generation模式；新identity开始即清上一组合所有数值。相同identity失败只可预览最后成功、明确标stale；chart/reference/explanation按section分别请求，并仅在snapshot共同事实验证兼容后拼接，不能假设服务器同包返回或新图+旧summary混合。
- [ ] **分页/viewport：** performance/as_of固定回传；reference指纹变化清空旧页，cursor拒绝后重新第一页。旧页相同ID异内容不静默覆盖。reference稳定但总input变化且共同Bar一致可更新图表，不能误判。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
pnpm -C apps/quant-web exec node --test tests/newowProductTypes.test.ts tests/useNewowProduct.test.ts
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(web): consume atomic Newow product snapshots`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 19: P5 — 九组合主图、辅助图与动作定位

**Files:**
- Create: `apps/quant-web/src/components/market/detail/newow/NewowProductWorkspace.vue`、`NewowProductChartStage.vue`、`newowProductChartPrimitives.ts`。
- Modify: `apps/quant-web/src/pages/market/MarketDetailPage.vue`；只按需要复用现有Kline/Stage接口。
- Create: `apps/quant-web/tests/NewowProductChartStage.test.ts`、`newowProductChartPrimitives.test.ts`。

**Interfaces / 依赖:** Task18 → 九组合可视主图；不复制公式/所有权。

- [ ] **图层模型测试：** 趋势B/A、震荡通道、主升浪MA35/45分别投影；同Bar CLEAR/BUILD保存两个ID与顺序，anchor_price绘图但reference_price不被覆盖。测试直接读取typed fixture，不在Web算MA。

```typescript
test('two oscillation actions survive the same timestamp', () => {
  const model = buildNewowProductChartModel(sameBarClearBuildFixture)
  assert.deepEqual(model.actions.map(x => x.kind), ['CLEAR', 'BUILD'])
  assert.notEqual(model.actions[0].id, model.actions[1].id)
})
```

新增 `buildNewowProductChartModel(response)` 在newowProductChartPrimitives.ts；fixture在本测试文件明确两个同时间有序动作。
- [ ] **组件接口：** ChartStage输入已验证response和选中的signal_id，发出 `select-signal`，不持有独立品种/周期选择；接入现有可见范围/加载回调，保持初始viewport和focus不被后到数据重置。
- [ ] **辅助层：** 三副图开关、warming/error独立；照妖镜明确“回看/会重绘”，杯柄仅D1并显示clean-room，60m/W1显示不适用而非暂无信号。全部非重绘hint可查看来源/确认时间。
- [ ] **旧视角回归：** newow分支不能把图层塞进generic ResearchOverlayId；view=trend、SuBing/HTDY Event Map与Free沿原隔离合同工作。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
pnpm -C apps/quant-web exec node --test tests/NewowProductChartStage.test.ts tests/newowProductChartPrimitives.test.ts
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(web): render nine Newow strategy-period combinations`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 20: P5 — 参考历史、统计与解释面板

**Files:**
- Create: `apps/quant-web/src/components/market/detail/newow/NewowReferencePanel.vue`、`NewowExplanationPanel.vue`。
- Modify: `NewowProductWorkspace.vue`、`src/utils/newowProductViewModel.ts`。
- Create: `apps/quant-web/tests/newowReferencePanel.test.ts`、`newowExplanationPanel.test.ts`。

**Interfaces / 依赖:** Task18/19 → 完整单品种历史处理；全由API结果驱动。

- [ ] **UI投影测试：** 0交易显示“—”、负中断浮动不消失、期初单列、同BarHint只Bar级、价offset不改变收益。参考与比较器使用不同panel/label。

```typescript
test('zero closed trades is not a zero-percent performance', () => {
  const model = buildNewowProductViewModel(noClosedTradesFixture)
  assert.equal(model.reference.winRateText, '—')
  assert.equal(model.reference.sumText, '—')
  assert.equal(model.reference.sumUnit, '百分点（简单相加）')
})
```

`buildNewowProductViewModel`在Task18定义并此处完善；noClosedTradesFixture明确计数0、三统计null、一个OPEN。
- [ ] **历史表：** 合约/策略/周期、entry/exit时间与参考价、状态、holding_bars、return、估值时点、提示展开；OPEN/CLOSED/中断/期初可筛但总统计不跟表格过滤悄悄变化。history分页仍保持固定样本summary。
- [ ] **历史→图表：** 按精确信号ID和bar_end定位；不在已加载窗口时通过新GET改变display窗口，保持performance不变；主动作选中与行选中来自一个selection authority。不存在的目标明确报不可用，不定位最近日期替代。
- [ ] **解释：** 展示规则/来源周期/时点、参考仓位、评分、ATR与第一行动token；无证据显示原因、不是0。五窗口期末“理论”结果单独显示，不出现额外CLEAR；历史点击不得用当前context冒充开仓依据。
- [ ] **固定提示：** 使用Spec的完整乐观口径说明；数字只格式化，不在前端配对/求和。首次错误清空数值，同identitystale有显眼时间标签；键盘可展开、定位、切表。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
pnpm -C apps/quant-web exec node --test tests/newowReferencePanel.test.ts tests/newowExplanationPanel.test.ts
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `feat(web): show reference histories and explicit explanations`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 21: P6 — 九组合浏览器与无回归验收

**Files:**
- Create: `apps/quant-web/e2e/newow-product.spec.mjs`、`newow-product.helpers.mjs`。
- Create generated baselines only after visual review: `apps/quant-web/e2e/newow-product.spec.mjs-snapshots/`。
- Test existing: `apps/quant-web/e2e/market-detail.spec.mjs`、`market-home.spec.mjs`。

**Interfaces / 依赖:** P4/P5 → AC01/06/08/09/13/15–19的可重现UI证据。

- [ ] **可控fixture网：** 拦截新GET及现有generic/Alert只读响应，未拦截外部请求直接失败；不调用运行中的真实API。fixture明确九组合、有同Bar双动作、中断亏损、OPEN、无entry黄色、0CLOSED、evidence_required、warm-up与revision。
- [ ] **九组合和viewport：** 每个test从独立初始页面开始；至少桌面1440×900、移动390×844。覆盖三个策略×三个周期的切换，不从桌面缩放成移动再复用状态。截图审阅后才建立baseline，不能反复更新快照掩盖布局bug。

```javascript
for (const strategy of ['trend', 'oscillation', 'main_rise']) {
  for (const frequency of ['1w', '1d', '60m']) {
    test(`${strategy}/${frequency} preserves reference statistics`, async ({ page }) => {
      await installNewowProductFixtures(page)
      await page.goto(`/market/chart?symbol=rb&view=newow&strategy=${strategy}&frequency=${frequency}&series_kind=actual_dominant`)
      const before = await page.getByTestId('newow-reference-summary').innerText()
      await page.getByTestId('newow-load-earlier').click()
      await expect(page.getByTestId('newow-reference-summary')).toHaveText(before)
    })
  }
}
```

本Task的helper负责固定响应和分页；Task19/20提供上述data-testid和“加载更早”可访问操作，不添加业务算法。
- [ ] **交互失败路径：** 旧请求晚回、参考cursor世代变化、identity错误、辅助不可用、旧trend深链、HTDY/SuBing Event focus、Free指标、键盘与窄屏历史详情；同时间双动作分别可点。首页网络计数仍旧bulk约束。
- [ ] **运行：** 独立视觉审查记录截图与实际结果；无原件的P3功能截图只能证明准确降级，不能替代其精确公式验收。

- [ ] **验证与复验：** 新测试先RED；实现后同一命令GREEN。

```bash
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/market-detail.spec.mjs e2e/market-home.spec.mjs
```

- [ ] **提交与Review：** `git diff --check`，只stage上述本Task改动，提交 `test(web): verify Newow product and existing detail journeys`；独立review给出Spec和quality结论，修复后重新验证。

---

## Task 22: P6 — 全量矩阵、规范回读与最终双轴Review

**Files:**
- Modify facts only: `TESTING.md`、`STATUS.md`、`docs/tasks/2026-09-05-newow-product-reference-trading-coverage.md`。
- Read/Test: 全部受影响Core/API/Web/OpenSpec及既有保护测试。

**Interfaces / 依赖:** 所有通过的工作包 → 正确的阶段结论；不是发布/Runtime授权。

- [ ] **冻结最终head并读回差异：** 确認没有migration、launchd、RQData下载、Scope、PushPlus、订单、外部LLM调用或未授权文件变动。记录最终HEAD/tree与工作区dirty状态；不能把docs PR合入当release。
- [ ] **执行全量矩阵：** 只用本地fixture环境，命令来自本次核对TESTING.md。

```bash
uv sync --project services/quant-api --locked
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q -m "not isolated_postgresql and not manual_acceptance" services/quant-api/tests
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q tests/engineering
uv run --project services/quant-api python -m ruff check services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports services/quant-api/app packages/quant-core/guiyi_quant
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short --branch
```

- [ ] **证据清单：** 已保留公式逐值回归与新政策fixture分开，local golden真正重放才记录PASS；18个旧OOS结果与9个W1执行阻塞保持历史状态，不能因本产品通过改成OOS_PASSED。无新migration则isolated PostgreSQL不适用，不连接production。
- [ ] **逐条核对AC01–28：** 见下表；P3任何范围内适用能力仍EVIDENCE_REQUIRED，阶段只能 `PARTIAL_PRODUCT / EVIDENCE_REQUIRED`，已验证纵向切片可以独立进入开发集成。
- [ ] **最终Review：** 同exact head独立Standards与Spec，无P1/P2；P3建议完整记录。任何修复后重跑受影响验证、读回新的head并复审；reviewer不能只信实现者结论。没有GitHub checks时记NO_CHECKS_REPORTED。
- [ ] **事实收口：** 仅全部能力与AC通过才能记 `NEWOW_PRODUCT_AND_REFERENCE_TRADING_COMPLETE / RELEASE_GATE_PENDING`。生产仍是当前真实tag，苏冰状态按其真实事实保留；没有用户新授权不main/tag/release、不Runtime promotion。

---

## 4. AC追踪矩阵

| AC | 主验收Task | 验证要点 |
|---|---|---|
| AC01 | 4、15、19、21 | 三策略三周期独立身份与完整视图 |
| AC02 | 0、5、11–13、22 | 原公式golden/当前证据与缺原件状态 |
| AC03 | 3、5 | 60m同日/W1零段/4001前缀完整分页 |
| AC04 | 4、5 | 非重绘prefix/batch/rebuild与区段隔离 |
| AC05 | 3、4、8 | warm-up不补entry、期初单列 |
| AC06 | 4、6、19、21 | 精确引用/同Bar CLEAR再BUILD |
| AC07 | 7、9、20 | hint不改数量或收益、空仓不丢hint |
| AC08 | 3、7、20 | 换月中断、负浮动、不跨价 |
| AC09 | 7、8、14、18、21 | 样本末不清仓、viewport独立 |
| AC10 | 4、6、8、19 | B/Low-High/MA45不误取绘图价 |
| AC11 | 8、15、20 | Decimal/串行化/舍入/空样本 |
| AC12 | 8、20 | CLOSED与OPEN/中断/期初分列 |
| AC13 | 13、20、21 | 比较器理论平仓隔离 |
| AC14 | 10、12、14、20 | 多周期as-of不借未来 |
| AC15 | 9、19、21 | 镜子回看隔离/杯柄D1确认 |
| AC16 | 16、17、21 | 旧D1、HTDY/SuBing深链/Free |
| AC17 | 14、15、18、21 | generation/指纹/失败/warming/stale |
| AC18 | 1、16、22 | 不新增外部副作用和交易域 |
| AC19 | 19–21 | 桌面移动键盘/历史图表联动 |
| AC20 | 22及每包 | exact-head完整适用验证+双轴Review |
| AC21 | 14–16 | section级计算边界与未请求零调用 |
| AC22 | 14–16 | 权威cutoff、夜盘、晚CLEAR/Hint/owner边界 |
| AC23 | 14–16 | 服务端P3来源白名单、值/owner/version/as-of负测 |
| AC24 | 14–16 | snapshot/cursor/修订/共同事实409 |
| AC25 | 14、16 | 32条/128MiB/32MiB/300秒LRU与bypass |
| AC26 | 14、16 | 共享重型并发1、FIFO等待2、5秒超时和取消释放 |
| AC27 | 15–16 | typed wire、错误脱敏、旧D1兼容 |
| AC28 | 16 | 后端30次冷热/修订/压力测量；P5/P6仍未测 |

## 5. 主要失败与恢复路径

| 失败 | 处理 |
|---|---|
| 源码与历史报告冲突 | 当前源码+测试代表实现；原件代表parity依据；只报告差异，不能用摘要改写事实 |
| P3原件/阈值/排序缺失 | 精确功能EVIDENCE_REQUIRED；不制造golden、不以通用技术分析补齐 |
| 主策略数据/owner/前缀冲突 | fail-closed，不以辅助图正常掩盖，不联网修数据 |
| 页面配对冲突 | 保留可验证主图诊断，参考区不可用；不自动找最近BUILD |
| 新引用规范导致旧D1合同变化 | 保留旧入口与实现，修新adapter，不放宽旧非法URL |
| 覆盖不完整或性能吃紧 | 显式资源/数据错误；不截断后假称全部历史，不建缓存服务绕过 |
| 数据修订时收到旧分页 | 409并清旧参考页，重取完整当前快照；不混两代统计 |
| review P1/P2 | 当前Task/包阻塞，修复+定向复验+复审；不自行豁免到最终通过 |
| 苏冰出现自然验收或生产故障 | 本计划不操作；分开记录/交给苏冰任务，不连带改变Newow参考规则 |

## 6. 实施授权与交付

2026-09-05 初始 Plan 的最小执行单元为 P0，该句仅保留历史。P0–P3已集成后，当前唯一实施范围为 P4 Tasks 14–16。普通commit/push/PR/合入develop遵守执行时Owner请求与AGENTS；源码分包Review、外部操作授权互不替代。此前v1.9.15任务的授权不继承到本项目。

每包交付只需：base/head/tree、改动文件、实际测试命令/结果、Review结论、coverage变化、剩余Gate、下一个独立工作包。只读/文档Task没有业务commit也要给出对应diff和审查结果，不伪造test count。

2026-09-05 的设计与 Plan 提交当时不意味任何业务 Task 已完成；该记录不得用于把当前实施重置到 P0。当前 P4 必须用 Tasks 14–16 的真实源码、测试和独立 Review 获得完成证据。

## 7. 来源与计划自审记录

本Plan基于批准Spec及 exact develop 核对的：`TESTING.md`、Web `package.json`、`marketDetail.ts`、`marketDetailRoute.ts`、`marketDetailPreferences.ts`、`actual_dominant_research.py`、`research_backtest.py`、`test_trend_detail_service.py`、newow `conftest.py`，并沿用Design已核对的primitive/API和资料来源。未使用外部通用策略知识补充未证公式。

自审需确认：原23个Task历史编号不改写，P4 Amendment由Tasks14–16覆盖AC21–28；参考交易与比较器无共享退出逻辑；新API参数/模型在本Plan唯一冻结；全部测试factory在对应Task明确新增，不冒称现有fixture；所有未来测试结果使用Expected而非既成事实；无收益真实性或生产运行完成承诺。
