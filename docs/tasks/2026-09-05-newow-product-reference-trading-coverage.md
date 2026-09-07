# Newow 产品与乐观参考交易 P0 覆盖与证据 Gate

日期：2026-09-05
状态：`P6_MATRIX_CANDIDATE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED / FINAL_DUAL_REVIEW_PENDING`（阶段事实仍只以 `STATUS.md` 为准）
边界：只记录批准范围、当前源码/测试入口和本地证据可用性；不修改公式，不重跑历史页面一致性，不授权 develop/main 集成、发布、生产数据、Runtime、通知或订单操作。

## 1. Plan execution identity

| 项 | 精确身份 |
|---|---|
| 执行包 | `P0 / Task 0 — 审批基线与证据可用性清单` |
| task branch / worktree | `feature/newow-product-reference-trading-p0` / `.worktrees/newow-product-reference-trading-v1` |
| execution BASE | `origin/develop@3431da7788835791949ddffcb025a24fba4a17f2` |
| docs source | `origin/docs/newow-product-reference-trading-v1@75e6fab90efe236990089c1ba31e476ea730aae7` |
| docs integration | PR `#345` merge `3431da7788835791949ddffcb025a24fba4a17f2`；Design 与 Plan 已进入 BASE |
| Design pre-execution blob | `dd65db8582962be202623437ac52d3a2b2735f7a` |
| Plan blob | `4f76e4fd0ec5067376bb31951907bd7c2f4e48e7` |
| Plan dated header | `2026-09-05`；保留原 header 和历史 metadata，不修改 Plan |
| Owner authorization used by this Task | Design `OWNER_APPROVED_FOR_IMPLEMENTATION`；只授权本 Task 的仓库文档/证据工作，不扩大任何外部操作权限 |

执行前 `HEAD` 与 BASE 一致，分支已跟踪 `origin/develop`，dirty state 为空。本地 `develop` worktree 仍在旧提交 `4f4754ed6df67a1d828e35b82fe2269d7f020469`，因此本 Task 不以本地 `develop` worktree 代替 controller 已 fresh fetch 的 `origin/develop` 身份，也不合入任何分支。

## 2. 证据集合与本轮核验口径

下表中的 evidence bundle 只引用 `full-local-evidence-manifest.json` 已明确登记的条目；不引用目录扫描结果。

| Bundle | manifest 中的精确条目 | 用途 |
|---|---|---|
| `M-SOURCE` | `sources/stock-detail-v3.2.82.html`；`sources/strategy-calc-v3.2.82.js` | 页面控制流与公开计算源码原件 |
| `M-CORE` | `analysis/core-parity-inputs.json`；`analysis/core-page-parity-results.json`；`analysis/multi-period-page-facts.json` | 27 个页面点的冻结输入、结果和多周期页面事实 |
| `M-REPLAY` | `analysis/collect_exact_page_cases.mjs`；`analysis/verify_exact_page_cases.py`；`analysis/verify_core_page_parity.py`；`analysis/kline-source-index.json` | 原件到逐点重放的采集/校验链 |
| `M-COMPOSITE` | `analysis/composite-reachability.json`；`analysis/verify_composite_reachability.py` | 13 格控制流及可达性 witness |
| `M-AI` | `analysis/ai-template-evidence.json`；`analysis/extract_ai_template_evidence.py` | 当前周日 16 组合和历史 A–E 来源映射 |
| `M-OPTIMIZER` | `analysis/page-optimizer-oracle.json`；`analysis/build_page_optimizer_oracle.mjs`；`sources/page-cases/600519-SH/day.json` | 五窗口页面 oracle、输入和排名结果 |
| `M-FUTURES` | `futures/newow-futures-evidence-20260904.json`；`futures/normalized-research-snapshot.json`；`futures/oos-cost-stress-matrix.json` | 期货迁移/研究摘要；不作为本阶段乐观参考交易实现证明 |

本地完整证据根按历史登记的逻辑身份 `newow-strategy-detail-research/v3.2.82-gap-closure` 定位；绝对主机路径不写入仓库。只以 manifest 的 133 个相对路径逐项读取，先拒绝绝对路径和 `..`，再要求普通非符号链接文件，比较 `byte_count` 和 SHA-256。结果为：

- manifest schema `newow-evidence-manifest-v2`，共 133 项，其中 captured 96、derived 37；
- `missing=0`、`mismatch=0`、`unsafe=0`；
- manifest 自身 SHA-256 为 `279aa0c3a88b6e6c5413387a57085dfe4c4d23a34befa751d95ced4c03be962f`；
- `analysis/source-registry.json` 与仓库 `evidence/source-registry.json` 均为 `0b9e841c9d6af50acfc9adb924f90d4eb161e127db641198301b74a45c1e7dab`；source registry 共 96 项，86 个 GET、10 个 POST；
- 未读取凭据、未联网、未重新采集、未复制原件内容，也未递归扫描用户目录。

这些结果只证明当前登记原件存在且字节身份未变。历史 `27/27 matched` 仍是既有研究结果，本 Task 没有执行其重放脚本，不能把上述 133/133 哈希核验写成新的公式测试或 page-parity 结论。

## 3. 功能覆盖表

状态口径：`ACTIVE_CODE_VERIFIED` 表示源码和测试入口已经存在并有当前代码证据；`RESEARCH_EVIDENCE_ONLY` 表示精确复刻结论仍只由已核对的冻结研究原件支撑，即使已有 bounded 产品包装也不升级为完整页面/期货 parity；`EVIDENCE_REQUIRED` 表示现有证据明确不足，不能用常识或相邻功能补齐。各行 retained source/test 与 blocker 记录当前 P3 package head 的实现事实，不把 P0 BASE 盘点冒充当前完成度。

| feature | applicable strategy-frequency | formula_version | retained source | test | local evidence manifest entry | evidence status | blocker |
|---|---|---|---|---|---|---|---|
| 趋势主策略 | `trend × 1w/1d/60m` | `newow_trend_band_page_v2` | `packages/quant-core/guiyi_quant/newow/trend_band.py`、`profile.py`、`product_adapters.py` | `services/quant-api/tests/newow/test_trend_band_page_v2.py`、`test_product_adapters.py`、`test_product_replay_invariants.py`；D1兼容见`test_trend_detail_service.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P1 已提供三周期frequency envelope、物理区段前缀与adapter；P4只消费，不改公式 |
| 震荡主策略 | `oscillation × 1w/1d/60m` | `newow_oscillation_hhv_llv10_page_v1` + `newow_hhv_llv_channel_page_v1` | `packages/quant-core/guiyi_quant/newow/oscillation_channel.py`、`product_adapters.py` | `services/quant-api/tests/newow/test_oscillation_channel.py`、`test_product_adapters.py`、`test_reference_trades.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P1/P2已冻结三周期adapter与同Bar`CLEAR → BUILD`；P4不得反转 |
| 主升浪主策略 | `main_rise × 1w/1d/60m` | `newow_main_rise_ma35_ma45_page_v1` | `packages/quant-core/guiyi_quant/newow/main_rise.py`、`product_adapters.py` | `services/quant-api/tests/newow/test_main_rise_page_v1.py`、`test_product_adapters.py`、`test_research_backtest.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P1已提供三周期adapter；主动作价格保持MA45 |
| S 跑 / D1–D3 | `trend/main_rise × 1w/1d/60m`；Hint only | `newow_escape_d123_page_v2` | `packages/quant-core/guiyi_quant/newow/escape_d123.py`、`product_adapters.py`；trend profile 与 main-rise bundle 均保留该身份 | `services/quant-api/tests/newow/test_escape_d123_page_v2.py`、`test_product_adapters.py`、`test_reference_trades.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | 已包装为`quantity_effect=none` Hint；不得改变BUILD/CLEAR |
| D4–D6 | `main_rise × 1w/1d/60m`；Hint only | `newow_buy_d456_page_v1` | `packages/quant-core/guiyi_quant/newow/main_rise.py` | `services/quant-api/tests/newow/test_main_rise_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | `Low×0.99` 仅为 Hint/绘图参考，不得替代 MA45 主动作价或产生加仓 |
| J 风险 | `main_rise × 1w/1d/60m`；Hint only | `newow_main_rise_j_reduce_page_v1` | `packages/quant-core/guiyi_quant/newow/main_rise.py` | `services/quant-api/tests/newow/test_main_rise_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | 只作风险 Hint，不得推导减仓比例或改变参考持有 |
| 4/7/11 | `main_rise × 1w/1d/60m`；结构 Hint | `newow_magic11_page_v1` | `packages/quant-core/guiyi_quant/newow/magic11.py`、`product_adapters.py`；main-rise bundle | `services/quant-api/tests/newow/test_magic11.py`、`test_product_adapters.py`、`test_main_rise_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | 已按物理区段重置并保留为结构Hint；不产生独立交易动作 |
| 主力控盘副图 | 三策略 × `1w/1d/60m`；共享解释层 | `newow_main_force_control_page_v1` | `packages/quant-core/guiyi_quant/newow/subplots.py`；P3 wrapper `product_auxiliary.py` | `services/quant-api/tests/newow/test_subplots_page_v1.py`、`test_product_auxiliary.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P3 Task 9 已按物理 owner 分段包装并保留独立 warming；“主力”不等于持仓/席位事实，也不产生 Action/Hint |
| 主力照妖镜副图 | 三策略 × `1w/1d/60m`；retrospective only | `newow_zhaoyao_mirror_repainting_page_v1` | `packages/quant-core/guiyi_quant/newow/subplots.py`；P3 wrapper `product_auxiliary.py` | `services/quant-api/tests/newow/test_subplots_page_v1.py`、`test_product_auxiliary.py`；禁止进入 causal signal 见 `test_research_backtest.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P3 Task 9 已将其只存于 `retrospective_layers`，保持 `repainting=true / formal_signal_eligible=false`；不进入 Hint/ReferenceTrade/收益 |
| 涨跌动能副图 | 三策略 × `1w/1d/60m`；共享解释层 | `newow_up_down_energy_page_v1` | `packages/quant-core/guiyi_quant/newow/subplots.py`；P3 wrapper `product_auxiliary.py` | `services/quant-api/tests/newow/test_subplots_page_v1.py`、`test_product_auxiliary.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P3 Task 9 已按物理 owner 分段包装；短区段显式 warming，不跨合约借值，也不产生 Action/Hint |
| 杯柄 | 当前产品映射 `trend × 1d`；`1w/60m = NOT_APPLICABLE` | `newow_cup_handle_v1`；`page_parity=false` | `packages/quant-core/guiyi_quant/newow/cup_handle.py`、`profile.py`；P3 wrapper `product_auxiliary.py` | `services/quant-api/tests/newow/test_cup_handle.py`、`test_trend_detail_service.py`、`test_product_auxiliary.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED`（clean-room） | P3 Task 9 只包装 confirmed D1 witness并保留 pivot/confirmed 时间；不得冒充牛哇私有 `cup_handle` 筛选公式 |
| 目标/吸筹显示选择 | 三策略共享 `1w/1d/60m` context | `newow_target_absorb_display_selection_page_v2`；guard `newow_price_guard_page_v3_1_6`；Guiyi适配 `guiyi_newow_target_absorb_segment_adapter_v1`；仅 weekly status-card override 增加 `newow_hhv_llv_channel_page_v1` | `packages/quant-core/guiyi_quant/newow/target_absorb_display.py`；原件仍为 `M-SOURCE`、冻结派生为 `M-CORE` | `services/quant-api/tests/newow/test_target_absorb_display.py`（page-only 可达分支逐支固定 golden、`best_available × 60m` 全包装器、JS Number/toFixed oracle 及正 raw 归零显示、W1 bar_end 严格递增/trading_day 不回退/latest authoritative fact 完整一致、surface 及全部 driver owner/frequency/time/as_of 隔离） | `sources/strategy-calc-v3.2.82.js`、`analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | 已实现已核对的日/周/best-available 选择，显式区分 shared-function 与 weekly status-card 覆盖，后者仅在 bar_end 严格递增、trading_day 不回退、同 owner、满10根且 supplied latest ProductBar 与 Task10 weekly slot 权威事实完整一致的周线前缀上复用 HHV/LLV10；guard 在有限安全域内仿真 pinned JS Number/toFixed，内部正 raw Decimal 保留且允许合法显示结果 `0.00`。既有 27/27 仅为 inherited evidence，本次未重放也未新增 27/27 声明。权威昨收来源/激活、0–11根统一 warm-up、原页面 completed/observed/effective 时序及真实期货跨 physical-contract/segment/rollover parity 仍为 `EVIDENCE_REQUIRED`/null，不得宣称完整产品或期货 parity |
| 综合决策 13 格 | 三策略共享多周期 context | `newow_composite_decision_page_v3_2_82_reachable_v1` | `packages/quant-core/guiyi_quant/newow/composite_explanation.py`；原件/可达性为 `M-SOURCE`、`M-COMPOSITE` | `services/quant-api/tests/newow/test_composite_explanation.py` | `sources/stock-detail-v3.2.82.html`、`analysis/composite-reachability.json`、`analysis/verify_composite_reachability.py` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | P3 Task 12 已按原控制流冻结 10 个显式页面分支（含 low-level absent-signal classifier 产生的 `neutral-neutral`）及 `neutral-bullish`/`neutral-bearish` 两个隐式 fallback；top-level 产品输入缺周期仍为 unavailable，不降级成 neutral；3 个 intended warning 分支保持不可达，不顺手修正；页面 label/position range 仅作解释事实，不是 StrategyAction、TargetPosition、手数或交易动作 |
| 确定性 / 方向 / 仓位区间 | 三策略共享多周期 context | `newow_composite_direction_page_v3_2_58`；`newow_composite_certainty_page_v3_2_59`；position range 归属 composite decision 身份 | `packages/quant-core/guiyi_quant/newow/composite_explanation.py`；冻结结果为 `M-CORE` | `services/quant-api/tests/newow/test_composite_explanation.py` | `analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | P3 Task 12 已冻结方向 6 分支、四分项、0/10 alignment cap 与页面仓位区间；确定性显式不是概率/胜率，仓位区间不是手数、TargetPosition 或订单；六组合输出 oracle 未冻结，不进入该结果 |
| ATR20/Close 波动率 | 三策略共享 context；只使用 Task 10 权威已完成 D1 前缀 | `newow_composite_volatility_mean_tr20_over_close_page_v3_2_59` | `packages/quant-core/guiyi_quant/newow/composite_explanation.py`；冻结结果为 `M-CORE` | `services/quant-api/tests/newow/test_composite_explanation.py` | `analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | P3 Task 12 已按页面把 OHLC/昨收先收窄为 finite JS Number，再用 binary Number 完成最多 20 个 TR 的顺序求和、简单均值、除以最后 Close 与 `Math.round` 一位小数；`100.975/99.025/100 -> 1.9 / low` 边界已冻结，超出 finite Number 域以稳定 `NEWOW_COMPOSITE_PAGE_NUMBER_OUT_OF_RANGE` fail-closed，合法 `1E100` 不泄漏 Decimal 异常；D1 同 owner、bar_end 与 trading_day 均须严格递增，不接受同交易日多 Bar；Task 12 `source_bars` 分开登记三周期 current decision facts 与实际最多 21 根 D1 volatility prefix 的 frequency/owner/source/count/首末 Bar/交易日/as-of/in-sample/repaint/input evidence，0–5 根保留可审计 warming range；显式不是 Wilder ATR，且不得反向修改主策略 Gate |
| 第一行动原则 | 三策略共享多周期 context | `newow_first_action_principle_page_v3_2_63` | `packages/quant-core/guiyi_quant/newow/composite_explanation.py`；冻结结果为 `M-CORE` | `services/quant-api/tests/newow/test_composite_explanation.py` | `analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | P3 Task 12 已按页面优先级实现 8 个确定性分支并逐支冻结完整 page level/title/detail；周空日多分支不复用其他分支的“逢高减仓”后缀；稳定 `rule_token` 继续明确标记 `GUIYI_CLEAN_ROOM / token_is_page_native=false`，不把页面 prose 冒充机器合同，且不产生交易动作 |
| 周日 16 组合 | 三策略共享 week/day context | `newow_trend_week_day_matrix_page_v3_2_49` | `packages/quant-core/guiyi_quant/newow/composite_explanation.py`；确定性提取为 `M-AI` | `services/quant-api/tests/newow/test_composite_explanation.py` | `analysis/ai-template-evidence.json`、`analysis/extract_ai_template_evidence.py`、`sources/stock-detail-v3.2.82.html` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | P3 Task 12 只迁移 16 个 input key 到 name/risk/position 的结构化映射；历史 A–E 月线依赖、AI copy、建议和订单语义不进入本阶段，AI copy 保持 `EVIDENCE_REQUIRED`/null |
| 五窗口页面比较器 | `oscillation × 1w/1d/60m`；独立 comparator | `newow_hhv_llv_window_optimizer_page_v1`；Guiyi 适配 `guiyi_newow_page_comparator_segment_adapter_v1` | `packages/quant-core/guiyi_quant/newow/page_comparator.py`；页面 oracle 为 `M-OPTIMIZER` | `services/quant-api/tests/newow/test_page_comparator.py`（frozen 601-bar 五窗口 raw Decimal/display/force-close/rank、inclusive HHV/LLV、同 Bar exit→re-entry、未实现盈亏参与回撤、stable tie 解释、真实 `NewowProductReader` dataset-level source identity、stable Bar fact duplicate/conflict、必填 owner authority、实际 source range/as-of/repaint/input status、latest-empty fail-closed、P2 OPEN 不受影响） | `analysis/page-optimizer-oracle.json`、`analysis/build_page_optimizer_oracle.mjs`、`sources/page-cases/600519-SH/day.json`、`sources/stock-detail-v3.2.82.html` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | P3 Task 13 已冻结 offline page-source 五窗口 kernel：内部保持 JS binary Number 计算，public 价格/收益/回撤/胜率/评分仅以 Decimal 投影。Guiyi 适配必须提供权威 physical-contract/segment 集，不从 observed Bars 推测 latest；每段独立重置，分开携带权威 owner 范围与实际 source Bar 范围/数量/来源身份/as-of/in-sample/repaint/input-snapshot 状态，默认最新权威区段，最新空区段不回退。期末合成估值仅在 comparator 内标记 `synthetic_terminal=true`，不产生 StrategyAction/CLEAR/ReferenceTrade、不汇总账户、不修改 P2。browser-final kline、DOM 渲染、browser tie golden 与原页期货 owner 行为仍为 `EVIDENCE_REQUIRED`/null；Guiyi futures adapter 显式 `page_parity=false`，且既有 27/27 仅为 inherited evidence，本次未重放也未新增 27/27 声明 |
| 页面诊断 token / 六组合评分映射 | 三策略共享解释层候选 | `UNFROZEN` | `packages/quant-core/guiyi_quant/newow/composite_explanation.py` 仅提供显式 gap/null；`core-page-parity-results` 明确 diagnostic token 无稳定机器合同 | `services/quant-api/tests/newow/test_composite_explanation.py`（只验证 fail-closed gap） | `analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `EVIDENCE_REQUIRED` | 原件只证明六组合算法/prose 输出存在，未冻结六组合输出 oracle，也不能推出稳定 diagnostic token、评分输入/排序或 AI copy；P3 Task 12 保持 `six_combo_output_oracle`、`stable_diagnostic_token_mapping`、`ai_copy` 为 `EVIDENCE_REQUIRED`/null，不宣称 exact/complete |

## 4. Gate 结论

- P1/P2 已按各自独立 Gate 集成；P3 Task 9/10 已完成，三个副图、D1杯柄和多周期 as-of 均有 active Core wrapper 与 focused tests。该事实不改变任何发布、Runtime 或外部操作状态。
- P3 Tasks 11–13 已有 active、typed、evidence-gated Core 入口和新的自有 golden/boundary tests，但仍为 `PARTIAL / RESEARCH_EVIDENCE_ONLY`：目标/吸筹、综合解释与五窗口各自列明的外部证据缺口继续阻塞完整页面/期货 parity，P3 package 不得据此整体宣称完整产品交付。
- 页面诊断 token / 六组合评分映射保持 `EVIDENCE_REQUIRED`；AI prose、历史 A–E 月线模板和六种私有服务端选股不进入本阶段 exact 实现。
- 133/133 哈希一致不是新的 `27/27 matched` 测试，不支持盈利、OOS、Paper、Shadow、Runtime 或真实交易结论。

P3 已通过 PR #349 集成到 `develop@c9d297b8318c1d4bdcfbfc1b4e2e46b55956e26c`；P2 为 PR #348。当前 P4 消费入口为 `product_query.py`、`product_reader.py`、`product_adapters.py`、`reference_trades.py`、`reference_statistics.py`、`product_auxiliary.py`、`context_alignment.py`、`target_absorb_display.py`、`composite_explanation.py`、`page_comparator.py`。

P4 当前候选已实现并定向验证 `product_service.py`、`product_reader.py`、`source_facts.py`、`snapshot_cache.py`、`resource_gate.py`、独立产品 schema 和同一路由 `/strategy-detail`：五个 section 按请求单独计算，reference 的权威 cutoff 与 viewport 分离，服务端只从已读 Bar/replay 构造来源事实，快照 token、游标、修订冲突和资源超限均有分类错误。目标/吸筹的昨收来源/调用时机、原页面期货 owner parity、browser-final K线/DOM/tie golden、AI copy、稳定诊断 token 与六组合 oracle 仍是具体外部证据缺口；它们阻塞对应精确子功能或 P6 完整复刻声明，不阻塞 P4 对缺口的准确降级。

P4 候选的局部实现提交为 `098a6b15c`（section 编排）、`7ba332325`（typed read-only API）、`c96430dc0`（缓存/资源/来源初版）、`22b121fc1`（首轮 Review 合同修复）、`44687e475`（扩展性能入口）和 `907179231`（剩余 scoped Review finding 修复）。`907179231` 回退了没有独立等价证据的 `_attach_hints` 索引改动；本包不以未证明优化改变冻结 Core。当前有效的影响范围证据为：P2/P3/P4/旧 D1 相关 pytest `506 passed, 1 skipped`，修改源定向 mypy clean，修改文件 ruff clean。`907179231a091f75398fc95037c493d5786ec7a8` 上隔离 fake MDS 的 nearest-rank P95 为：4001根60m冷请求30次 `171.381ms`、逐事实重验后缓存命中30次 `73.734ms`、8001根压力30次 `322.930ms`；601根阶段样本的读取+验证 `5.551ms`、replay `14.052ms`、ReferenceProjection `0.103ms`、reference总计 `21.510ms`、comparator总计 `25.856ms`，90根历史修订重验30次 `8.753ms`、序列化30次 `3.102ms`，响应 `289172 bytes`、RSS high-water `223641600 bytes`。排队、取消、最后消费者语义使用确定性并发测试而非时间P95。该性能证据只覆盖后端 fake-MDS 阶段，不是浏览器、真实 MDS 或真实工作站验收；最终候选若相关源码/fixture变化必须使相应证据失效并补跑。

独立 Sol/high reviewer 在 exact head `d2322c246ef5d9cc2507f7caea38fc3df6c9b322` 完成 Spec 与 Standards/Quality scoped 复审，两轴均为 PASS、P1/P2/P3 finding 均为 none；审阅复用了上述 exact source tree 的有效测试/性能证据并另行确认 `git diff --check` clean，结论为 `REVIEW_COMPLETE / 允许集成 develop`。该结论只覆盖 P4 包，不扩大到 P5/P6、完整 page parity、OOS、发布或 Runtime。

P4 集成本身不授权后续 P5 Web、P6 全项目验收、真实工作站性能、RQData/Canonical/DB/Redis 写入、Runtime、通知、main/tag/release 或交易操作；P5 的执行范围来自后续独立的 owner 授权。

P5 Tasks 17–20 已在候选分支 `feature/newow-product-reference-trading-p5` 实现：`c731756f1` 完成新视角、路由/偏好 v2 与首页入口，`cb9c93cec` 完成 typed parser/client、section 请求隔离、有界分页与 409/429 生命周期，`9226df639` 完成九组合主图、同 Bar 动作、辅助序列与 Hint 来源，`09dde38ca` 完成参考历史/统计、精确信号定位、解释与独立比较器，`33ba9b7cb` 关闭包级 review 发现的 pair-specific snapshot、busy/cancelled stale、409 跨 section 失效、时间因果校验和白名单权威边界，`c70ce87c6` 补齐请求未携 token 时从当前 section 保留事实解析并失效被拒世代的确定性竞态，`32f6acf19` 进一步在可重建 409 后取消并推进同旧 token 的其他在途 section 世代，`3939e19de` 最终把未显式携 token 的请求绑定到 retained section generation，关闭其晚到污染重建事实的竞态。Task 级 finding 与最终包级 finding 均已修复并完成 scoped re-review；最终影响范围为 `114/114`、候选 Web 全量为 `412 passed, 1 skipped, 0 failed`，Alert Rule ownership、build/typecheck/topology、OpenSpec、secret 与 diff checks 通过。最终 Spec 与 Standards/Quality 均为 PASS，Critical/Important/Minor finding 均为 0；这只形成 P5 候选的 `REVIEW_COMPLETE`，不代表已合入 develop、P6、发布或 Runtime。

P5 浏览器 smoke 使用本地 route-intercept fixture，以真实浏览器逐项切换九组合并检查 409 单次恢复、429 单次 busy、参考分页/定位、解释 evidence-required、桌面及 `390×844` 移动端布局。该证据只证明候选 UI 与错误呈现，不是 P6 新建 E2E、真实 MDS、真实工作站性能、页面原站 parity 或 production 验收；被刻意注入的 409/429 是预期控制台 error。P3 的目标/吸筹、原页面期货 owner、browser-final/tie golden、AI copy、稳定诊断 token 与六组合 oracle 缺口继续保留。

P5 已经 PR #351 集成到 `develop@242368b893256c48656f047178c213d1cf2d012f`。P6 Task 21 候选 `3e3c81df0c2fb53a3f64791cf94aa95b72f821e1` / tree `e6e1705f6a225e1d3e9e080bc84adf5ee392a5aa` 已完成 tracked browser/visual fixture Gate；Task 22 初始全量矩阵与 AC ledger 见下节。P6 的仓库候选、完整 Newow 产品、release、Runtime 和真实工作站性能继续分别判断。

## 5. Task 22 初始矩阵与修复事实

初始矩阵在 `origin/develop@242368b893256c48656f047178c213d1cf2d012f` 之上的 P6 产品候选执行。各命令分别记账，不合并重叠 suite 数量：

| 命令 | exit / 结果 | wall time |
|---|---|---:|
| `uv sync --project services/quant-api --locked` | `0` | `2.12s` |
| backend pytest excluding isolated/manual | `0`; `2274 passed, 4 skipped, 15 deselected` | `266.14s` |
| `pytest -q tests/engineering` | `1`; `73 passed, 1 failed` | `53.98s` |
| Ruff | `0`; all checks passed | `0.52s` |
| Mypy | `0`; 128 source files | `6.83s` |
| `check:alert-rules` | `0` | `0.64s` |
| Web unit | `0`; `424 passed, 1 skipped` | `2.49s` runner |
| Web build | `0`; 3,075 modules, topology passed | `3.57s` |
| full Playwright | `0`; `109 passed` | `1.7m` runner |
| OpenSpec strict | `0`; `9 passed, 0 failed` | `0.95s` |
| secret scan | `0`; finding count 0 | `0.45s` |
| `git diff --check` / status | `0`; tracked tree initially clean | `<0.01s` each |

唯一失败是 `ACTIVE_MARKET_ROUTE_OWNERS` 仍列七条 route，未包含 P4 已加入的只读 `GET /api/v1/market/newow/strategy-detail -> app.api.market_newow:newow_strategy_detail`。该缺口已存在于本轮 `origin/develop`，P6 Web diff 未改后端路由或工程测试。最小修复只补精确 method/path/owner 三元组；原失败用例随后 `1 passed in 0.76s`，完整 `test_canonical_consistency.py` 为 `13 passed in 1.68s`。最终 exact-tree 全矩阵和独立双轴 Review 仍是 AC20 Gate。

## 6. AC01–28 ledger

`PASS` 表示该 AC 的当前仓库合同已有具体代码/测试/browser 或可复用 evidence；它不升级缺失的原页面证据。`BLOCKED` 表示仍需外部证据或最终 Review。

| AC | 状态 | 证据 / 剩余边界 |
|---|---|---|
| AC01 | `PASS` | `test_product_adapters.py`、`test_market_newow_product_api.py`、Task 21 九组合 browser cases。 |
| AC02 | `BLOCKED / EVIDENCE_REQUIRED` | 主公式现役 golden/adapter 回归与 M-SOURCE/M-CORE/M-REPLAY 保留；页面诊断 token、六组合输出 oracle/评分排序、AI copy 等未冻结，不能宣称完整 page parity。 |
| AC03 | `PASS` | `test_product_reader.py` 与 `test_product_replay_invariants.py` 覆盖 60m 同日、W1 零 Bar owner 段和 4001 前缀分页。 |
| AC04 | `PASS` | `test_product_adapters.py`、`test_product_replay_invariants.py` 的 prefix/batch/rebuild/owner 隔离。 |
| AC05 | `PASS` | reader/adapter/reference-statistics 测试覆盖 warm-up BUILD 不补 entry 与期初单列。 |
| AC06 | `PASS` | `test_reference_trades.py` 与 Task 21 same-Bar CLEAR→BUILD 精确双 ID 定位。 |
| AC07 | `PASS` | `test_reference_interruptions.py`、`test_product_auxiliary.py`、reference panel tests 证明 Hint 不改交易和空仓 Hint 保留。 |
| AC08 | `PASS` | reader/interruption tests 与 browser reference rows 覆盖中断、负浮动和禁止跨价。 |
| AC09 | `PASS` | reference/service/composable/browser pagination 证明样本末不 CLEAR、统计与 viewport 独立。 |
| AC10 | `PASS` | adapter/reference tests 与 fixture semantic validator 分别校验 B、Low/High、MA45，拒绝绘图锚点替代。 |
| AC11 | `PASS` | `test_reference_statistics.py`、API Decimal serializer、Web null/舍入显示测试。 |
| AC12 | `PASS` | reference summary/API/Web 将 CLOSED、OPEN、中断、期初分列，零 CLOSED 保持 null/“—”。 |
| AC13 | `PASS` | `test_page_comparator.py`、Explanation panel 与 browser comparator case 保持 synthetic terminal 隔离。 |
| AC14 | `PASS` | `test_context_alignment.py`、service cutoff tests、解释 source-bar browser evidence。 |
| AC15 | `PASS` | auxiliary/Core tests 与 browser repaint disclosure；杯柄仅 confirmed D1，其他周期 not-applicable。 |
| AC16 | `PASS` | readonly compatibility tests、route tests、Task 21 Legacy/HTDY/SuBing/Free/Home journeys。 |
| AC17 | `PASS` | service/cache/API/composable/browser tests 覆盖 generation、revision、409/429、warming/stale 与失败清理。 |
| AC18 | `PASS` | `test_product_readonly_compatibility.py`、仓库受控面 diff 扫描；无新增外部副作用或交易域。 |
| AC19 | `PASS` | Task 21 desktop/mobile/keyboard/reference-locate/marker selection 与截图 evidence。 |
| AC20 | `BLOCKED / FINAL_DUAL_REVIEW_PENDING` | 初始全矩阵仅 stale route inventory 失败且已定向关闭；仍须在文档候选 exact tree 完整复跑并完成 Standards/Spec 独立 Review。 |
| AC21 | `PASS` | `test_product_service.py` spy、Web chart-first browser case；未请求 section 零调用。 |
| AC22 | `PASS` | service cutoff/Calendar/Session/night trading-day tests；晚 CLEAR/Hint/owner 不污染早期快照。 |
| AC23 | `PASS` | `test_product_source_facts.py` 与 API 负测校验来源白名单、值/owner/version/as-of；缺项准确降级。 |
| AC24 | `PASS` | snapshot/cache/inflight/API/composable/browser 409 tests 覆盖 token/cursor/revision/共同事实冲突和一次重建。 |
| AC25 | `PASS` | `test_product_snapshot_cache.py`、readonly/performance tests 覆盖 32 entries/128MiB/32MiB/300s LRU、bypass 与 cache-off 等价。 |
| AC26 | `PASS` | `test_product_resource_gate.py`、`test_product_inflight.py` 覆盖并发 1、FIFO waiters 2、5s timeout、取消/最后消费者释放；chart 不等待。 |
| AC27 | `PASS` | typed API/schema/客户端 parser 与旧 D1 compatibility tests；内部错误固定脱敏。 |
| AC28 | `PASS` | `test_product_performance.py` 保留 backend fake-MDS 30 次冷热/修订/压力入口；Task 21/22 提供 route-fixture browser timing。`REAL_WORKSTATION_MDS_PERFORMANCE = NOT_RUN / PENDING`，不由 fixture 冒充。 |

## 7. 当前 Gate 结论

- P6 现为全矩阵候选，只有 AC20 的最终 exact-tree matrix 与独立 Standards/Spec Review 尚待关闭。
- 即使 AC20 后续通过，产品状态也只能是 `P6_COMPLETE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED`；AC02 所列 P3 原件缺口阻止 `NEWOW_PRODUCT_AND_REFERENCE_TRADING_COMPLETE` 与笼统 `page_parity=true`。
- 既有 18 个 D1/60m OOS 结果和 9 个 W1 执行事实阻塞保持历史 evidence 状态；本轮产品测试不能改写为 `OOS_PASSED`。
- `REAL_WORKSTATION_MDS_PERFORMANCE = NOT_RUN / PENDING`。本轮不连接或切换 active services，不执行 RQData、Canonical、production DB/Redis、Scope、notification、account/order/fill/ledger、Runtime、main/tag/release。
