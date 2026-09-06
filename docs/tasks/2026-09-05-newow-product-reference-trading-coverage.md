# Newow 产品与乐观参考交易 P0 覆盖与证据 Gate

日期：2026-09-05
状态：`P0_TASK_0_SCOPE_AND_EVIDENCE_MAPPED`
边界：只记录批准范围、当前源码/测试入口和本地证据可用性；不修改公式，不重跑历史页面一致性，不授权集成、发布、生产数据、Runtime、通知或订单操作。

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

状态口径：`ACTIVE_CODE_VERIFIED` 表示 BASE 中保留了对应源码和测试入口，不表示本 Task 重跑了测试；`RESEARCH_EVIDENCE_ONLY` 表示本地原件已通过 manifest 身份核验但 BASE 没有 active 产品实现；`EVIDENCE_REQUIRED` 表示现有证据明确不足，不能用常识或相邻功能补齐。

| feature | applicable strategy-frequency | formula_version | retained source | test | local evidence manifest entry | evidence status | blocker |
|---|---|---|---|---|---|---|---|
| 趋势主策略 | `trend × 1w/1d/60m` | `newow_trend_band_page_v2` | `packages/quant-core/guiyi_quant/newow/trend_band.py`、`profile.py` | `services/quant-api/tests/newow/test_trend_band_page_v2.py`；D1 product 回归见 `test_trend_detail_service.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P1 尚需显式 frequency envelope、物理区段前缀和三周期 adapter；不阻塞 P1/P2 开始 |
| 震荡主策略 | `oscillation × 1w/1d/60m` | `newow_oscillation_hhv_llv10_page_v1` + `newow_hhv_llv_channel_page_v1` | `packages/quant-core/guiyi_quant/newow/oscillation_channel.py` | `services/quant-api/tests/newow/test_oscillation_channel.py`、`test_research_backtest.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P1 尚需三周期 product adapter；P2 须保留同 Bar `CLEAR → BUILD`，不阻塞 P1/P2 开始 |
| 主升浪主策略 | `main_rise × 1w/1d/60m` | `newow_main_rise_ma35_ma45_page_v1` | `packages/quant-core/guiyi_quant/newow/main_rise.py` | `services/quant-api/tests/newow/test_main_rise_page_v1.py`、`test_research_backtest.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P1 尚需三周期 product adapter；主动作价格须保持 MA45，不阻塞 P1/P2 开始 |
| S 跑 / D1–D3 | `trend/main_rise × 1w/1d/60m`；Hint only | `newow_escape_d123_page_v2` | `packages/quant-core/guiyi_quant/newow/escape_d123.py`；trend profile 与 main-rise bundle 均保留该身份 | `services/quant-api/tests/newow/test_escape_d123_page_v2.py`、`test_main_rise_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P1/P3 需包装为 `quantity_effect=none` 的 Hint；不得改变 BUILD/CLEAR |
| D4–D6 | `main_rise × 1w/1d/60m`；Hint only | `newow_buy_d456_page_v1` | `packages/quant-core/guiyi_quant/newow/main_rise.py` | `services/quant-api/tests/newow/test_main_rise_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | `Low×0.99` 仅为 Hint/绘图参考，不得替代 MA45 主动作价或产生加仓 |
| J 风险 | `main_rise × 1w/1d/60m`；Hint only | `newow_main_rise_j_reduce_page_v1` | `packages/quant-core/guiyi_quant/newow/main_rise.py` | `services/quant-api/tests/newow/test_main_rise_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | 只作风险 Hint，不得推导减仓比例或改变参考持有 |
| 4/7/11 | `main_rise × 1w/1d/60m`；结构 Hint | `newow_magic11_page_v1` | `packages/quant-core/guiyi_quant/newow/magic11.py`；main-rise bundle | `services/quant-api/tests/newow/test_magic11.py`、`test_main_rise_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P3 需按物理区段重置并保留为结构解释；不产生独立交易动作 |
| 主力控盘副图 | 三策略 × `1w/1d/60m`；共享解释层 | `newow_main_force_control_page_v1` | `packages/quant-core/guiyi_quant/newow/subplots.py` | `services/quant-api/tests/newow/test_subplots_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P3 Task 9 尚无 product wrapper；“主力”不等于持仓/席位事实 |
| 主力照妖镜副图 | 三策略 × `1w/1d/60m`；retrospective only | `newow_zhaoyao_mirror_repainting_page_v1` | `packages/quant-core/guiyi_quant/newow/subplots.py` | `services/quant-api/tests/newow/test_subplots_page_v1.py`；禁止进入 causal signal 见 `test_research_backtest.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P3 必须保持 `repainting=true / formal_signal_eligible=false`，不得进入 Hint/ReferenceTrade/收益 |
| 涨跌动能副图 | 三策略 × `1w/1d/60m`；共享解释层 | `newow_up_down_energy_page_v1` | `packages/quant-core/guiyi_quant/newow/subplots.py` | `services/quant-api/tests/newow/test_subplots_page_v1.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED` | P3 Task 9 尚无 product wrapper；短区段须 unavailable，不跨合约借值 |
| 杯柄 | 当前产品映射 `trend × 1d`；`1w/60m = NOT_APPLICABLE` | `newow_cup_handle_v1`；`page_parity=false` | `packages/quant-core/guiyi_quant/newow/cup_handle.py`、`profile.py` | `services/quant-api/tests/newow/test_cup_handle.py`、`test_trend_detail_service.py` | `M-SOURCE`、`M-CORE`、`M-REPLAY` | `ACTIVE_CODE_VERIFIED`（clean-room） | P3 只包装 confirmed D1 witness；不得冒充牛哇私有 `cup_handle` 筛选公式 |
| 目标/吸筹显示选择 | 三策略共享 `1w/1d/60m` context | `newow_target_absorb_display_selection_page_v2`；guard `newow_price_guard_page_v3_1_6`；Guiyi适配 `guiyi_newow_target_absorb_segment_adapter_v1`；仅 weekly status-card override 增加 `newow_hhv_llv_channel_page_v1` | `packages/quant-core/guiyi_quant/newow/target_absorb_display.py`；原件仍为 `M-SOURCE`、冻结派生为 `M-CORE` | `services/quant-api/tests/newow/test_target_absorb_display.py`（page-only 可达分支逐支固定 golden、`best_available × 60m` 全包装器、JS Number/toFixed oracle 及正 raw 归零显示、W1 bar_end 严格递增/trading_day 不回退/latest authoritative fact 完整一致、surface 及全部 driver owner/frequency/time/as_of 隔离） | `sources/strategy-calc-v3.2.82.js`、`analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json` | `PARTIAL / RESEARCH_EVIDENCE_ONLY` | 已实现已核对的日/周/best-available 选择，显式区分 shared-function 与 weekly status-card 覆盖，后者仅在 bar_end 严格递增、trading_day 不回退、同 owner、满10根且 supplied latest ProductBar 与 Task10 weekly slot 权威事实完整一致的周线前缀上复用 HHV/LLV10；guard 在有限安全域内仿真 pinned JS Number/toFixed，内部正 raw Decimal 保留且允许合法显示结果 `0.00`。既有 27/27 仅为 inherited evidence，本次未重放也未新增 27/27 声明。权威昨收来源/激活、0–11根统一 warm-up、原页面 completed/observed/effective 时序及真实期货跨 physical-contract/segment/rollover parity 仍为 `EVIDENCE_REQUIRED`/null，不得宣称完整产品或期货 parity |
| 综合决策 13 格 | 三策略共享多周期 context | `newow_composite_decision_page_v3_2_82` | 无 active Core；原件/可达性为 `M-SOURCE`、`M-COMPOSITE` | BASE 无产品测试 | `sources/stock-detail-v3.2.82.html`、`analysis/composite-reachability.json`、`analysis/verify_composite_reachability.py` | `RESEARCH_EVIDENCE_ONLY` | P3 Task 12 尚需按原控制流实现与枚举测试；3 个 warning 分支不可顺手修正，当前不能宣称产品完成 |
| 确定性 / 方向 / 仓位区间 | 三策略共享多周期 context | `newow_composite_decision_page_v3_2_82` 下的页面规则；独立子版本尚未冻结 | 无 active Core；冻结结果为 `M-CORE` | BASE 无产品测试 | `analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `RESEARCH_EVIDENCE_ONLY` | P3 Task 12 需核对四分项、cap、方向与仓位映射并冻结子身份；分数不是胜率，仓位区间不是手数 |
| ATR20/Close 波动率 | 三策略共享 context；使用已完成 D1 输入 | `newow_composite_decision_page_v3_2_82` 下的 volatility 规则；独立子版本尚未冻结 | 无 active 产品入口；冻结结果为 `M-CORE` | BASE 无产品测试 | `analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `RESEARCH_EVIDENCE_ONLY` | P3 Task 12 需核对 ATR 定义、分档和缺失输入；不得反向修改主策略 Gate |
| 第一行动原则 | 三策略共享多周期 context | `newow_composite_decision_page_v3_2_82` 下的 first-action 规则；独立子版本尚未冻结 | 无 active Core；冻结结果为 `M-CORE` | BASE 无产品测试 | `analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `RESEARCH_EVIDENCE_ONLY` | P3 Task 12 需核对优先级与稳定 token 后实现；不能只复用自然语言 |
| 周日 16 组合 | 三策略共享 week/day context | 当前 source branch/token 表已冻结；产品 formula_version 尚未冻结 | 无 active Core；确定性提取为 `M-AI` | BASE 无产品测试 | `analysis/ai-template-evidence.json`、`analysis/extract_ai_template_evidence.py`、`sources/stock-detail-v3.2.82.html` | `RESEARCH_EVIDENCE_ONLY` | P3 Task 12 只能迁移 16 个输入分支与 token/仓位区间；历史 A–E 的月线依赖不进入本阶段 |
| 五窗口页面比较器 | `oscillation × 1w/1d/60m`；独立 comparator | `newow_hhv_llv_window_optimizer_page_v1` | 无 active Core；页面 oracle 为 `M-OPTIMIZER` | BASE 无产品测试 | `analysis/page-optimizer-oracle.json`、`analysis/build_page_optimizer_oracle.mjs`、`sources/page-cases/600519-SH/day.json`、`sources/stock-detail-v3.2.82.html` | `RESEARCH_EVIDENCE_ONLY` | P3 Task 13 必须核对信号、排序/并列、胜率/回撤与同 Bar 规则；期末理论平仓不得写入 ReferenceTrade，当前不能宣称产品完成 |
| 页面诊断 token / 六组合评分映射 | 三策略共享解释层候选 | `UNFROZEN` | 无 active Core；`core-page-parity-results` 明确 diagnostic token 无稳定机器合同 | BASE 无产品测试 | `analysis/core-page-parity-results.json`、`sources/stock-detail-v3.2.82.html` | `EVIDENCE_REQUIRED` | 原件只证明页面 prose/输出存在，不能推出稳定 token、评分规则、输入或排序；P3 Task 12 对该子功能不能宣称 exact/complete |

## 4. Gate 结论

- P1/P2 可以在当前批准范围内继续：三主策略及 D/J/4-7-11 的源码与测试入口保留，完整本地证据包的登记字节身份已核验；P0 没有发现阻塞 P1/P2 开始的证据缺口。
- P3 不能据此整体宣称完成。目标选择、13 格、确定性/方向/ATR/first-action、16 组合和五窗口仍只有研究证据，没有 active 产品入口与 Task 11–13 的新 golden tests。
- 页面诊断 token / 六组合评分映射保持 `EVIDENCE_REQUIRED`；AI prose、历史 A–E 月线模板和六种私有服务端选股不进入本阶段 exact 实现。
- 133/133 哈希一致不是新的 `27/27 matched` 测试，不支持盈利、OOS、Paper、Shadow、Runtime 或真实交易结论。

本 Task 的下一 Gate 是独立 Review 本 coverage 与 Design metadata；通过后才可按 Plan 进入后续 P0/P1 Task，不自动合入 `develop`。
