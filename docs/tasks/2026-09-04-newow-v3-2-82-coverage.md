# 牛哇 v3.2.82 功能覆盖与复刻状态

状态：`CODE_COMPLETE / REAL_WEEKLY_OOS_GATE_PENDING / FINAL_REVIEW_PENDING`

本表把页面观察、手册主张、归一实现和期货迁移证据分开。唯一状态集为 `OBSERVED_EXACT`、`REPRODUCED_EXACT`、`BEHAVIOR_INFERRED`、`CLEANROOM_IMPLEMENTED`、`UNKNOWN`、`REJECTED`。其中推断不能冒充页面公式；`UNKNOWN` 与 `REJECTED` 均没有实现入口。

外部证据根：`newow-strategy-detail-research/v3.2.82-gap-closure`
证据清单 SHA-256：`cf02e7489d322a5937c251feb6f8598f754b6131f991a7be340188bd7f5a4bc4`（129 文件，已离线 verify）

| Feature | Current source/version | Evidence status | Formula identity | Implementation entry | Stock evidence | Futures evidence | Remaining gate |
|---|---|---|---|---|---|---|---|
| 首页功能与策略入口 | index.html v3.2.82 | OBSERVED_EXACT | page navigation and legacy filters | none | 首页匿名截图与静态源码 | 不适用 | 产品导航壳不是策略公式，本设计仅作证据入口 |
| 股票详情页与多周期切换 | stock_detail.html static v3.2.63 under v3.2.82 site | CLEANROOM_IMPLEMENTED | page detail orchestration | services/quant-api/app/market_data/newow/trend_detail_service.py；apps/quant-web/src/components/market/detail/TrendDetailWorkspace.vue | 3 指数加 6 股票，week/day/60min 共 27 点 | actual_dominant 1d/1w/60m 只读详情事实 | 不复制牛哇产品壳和建议文案 |
| S跑与 D1-D3 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_escape_d123_page_v2 | packages/quant-core/guiyi_quant/newow/escape_d123.py | 9 标的旧金样本逐值 exact | actual_dominant D1 及 detail API 已实现 | 公式 Gate 已关闭 |
| D4-D6 建仓标记 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_buy_d456_page_v1 | packages/quant-core/guiyi_quant/newow/main_rise.py | 9 标的旧金样本逐值 exact | actual_dominant D1 及 detail API 已实现 | 公式 Gate 已关闭 |
| 趋势黄蓝带 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_trend_band_page_v2 | packages/quant-core/guiyi_quant/newow/trend_band.py | 3 指数加 6 股票旧金样本 exact；v3.2.82 27 点回归 | rb/sc/m 的 1d/60m OOS 已运行；1w 失败关闭 | 周线 execution-limit 合同 Gate |
| 震荡策略 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_oscillation_hhv_llv10_page_v1 | packages/quant-core/guiyi_quant/newow/oscillation_channel.py | 9 标的旧金样本 HHV10/LLV10 与状态 exact | rb/sc/m 的 1d/60m OOS 已运行；1w 失败关闭 | 周线 execution-limit 合同 Gate |
| 主升浪 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_main_rise_ma35_ma45_page_v1 | packages/quant-core/guiyi_quant/newow/main_rise.py | 9 标的旧金样本 MA35/MA45、J、信号 exact | rb/sc/m 的 1d/60m OOS 已运行；1w 失败关闭 | 周线 execution-limit 合同 Gate |
| 杯柄形态 primitive | 手册加详情页 v3.2.63 | CLEANROOM_IMPLEMENTED | newow_cup_handle_v1 | packages/quant-core/guiyi_quant/newow/cup_handle.py | 股票形态样本和 causality 测试已有 | actual_dominant D1 研究 primitive 已有 | 不能宣称当前服务端 cup_handle 筛选 exact |
| 11 周期 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_magic11_page_v1 | packages/quant-core/guiyi_quant/newow/magic11.py | 516 markers 与 3240 count lines exact | 主升浪组合与 detail API 内可复算 | 公式 Gate 已关闭 |
| 主力控盘副图 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_main_force_control_page_v1 | packages/quant-core/guiyi_quant/newow/subplots.py | 9 标的数值与状态 exact | 研究 primitive 可复算 | 已纳入 diagnostic facts/token |
| 照妖镜副图 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_zhaoyao_mirror_repainting_page_v1 | packages/quant-core/guiyi_quant/newow/subplots.py | 9 标的逐值 exact | repainting，只允许研究解释 | diagnostic formal input 显式拒绝 |
| 涨跌动能副图 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_up_down_energy_page_v1 | packages/quant-core/guiyi_quant/newow/subplots.py | 9 标的逐值 exact | 研究 primitive 可复算 | 公式 Gate 已关闭 |
| 目标价与吸筹价原始通道 | strategy-calc.js v1.0.9, query v3.2.82 | CLEANROOM_IMPLEMENTED | newow_target_absorb_hhv_llv10_page_v1 | packages/quant-core/guiyi_quant/newow/price_channel.py::calculate_price_channel | v3.2.82 的 27/27 页面末值与 HHV10/LLV10 一致 | actual_dominant 1d/1w/60m 各 owner segment 可复算 | 公式 Gate 已关闭 |
| 目标价与吸筹价展示选择 | strategy-calc.js v1.0.9, query v3.2.82 | CLEANROOM_IMPLEMENTED | newow_target_absorb_display_selection_page_v1 | packages/quant-core/guiyi_quant/newow/price_channel.py::select_display_prices | 日周状态、突破升级、fallback、昨收 clamp 与分支 token 测试 | 不进入期货信号 | 已在 API/Web 只读展示 |
| 参数比较器页面口径 | stock_detail.html v3.2.63 | CLEANROOM_IMPLEMENTED | newow_hhv_llv_window_optimizer_page_v1 | packages/quant-core/guiyi_quant/newow/price_channel.py::rank_page_channel_windows | 601 根页面响应离线 JS oracle，五窗口逐字段与排名 parity | `trustworthy_for_research=false`，禁止晋升 | 身份隔离 Gate 已关闭 |
| 参数比较器因果研究口径 | 归一设计 v1 | CLEANROOM_IMPLEMENTED | newow_hhv_llv_window_optimizer_causal_v1 | packages/quant-core/guiyi_quant/newow/price_channel.py::rank_causal_channel_windows | 页面偏差的 clean-room 修正，不宣称页面公式 | completed-Bar、next-open、显式手续费/tick/涨跌停、rollover 与 prefix 合同测试 | 1w execution-limit 合同 Gate |
| 页面同 Bar 无成本比较器直接晋升可信策略 | stock_detail.html v3.2.63 | REJECTED | none | none | 页面执行时序和无成本口径已冻结 | 不迁移 | 因违反因果与成本边界而永久拒绝；只允许另建 causal-research 身份 |
| 综合决策 13 格矩阵 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_composite_decision_page_v3_2_82 | packages/quant-core/guiyi_quant/newow/composite_decision.py::calculate_composite_decision | 13 个 source witness 执行页面控制流；10 个 key 可达、3 个 warning key 不可达；6 只个股页面输出逐字段冻结 | completed D1 actual_dominant 组合事实可复算 | 公式 Gate 已关闭 |
| 综合决策不可达 warning 修正 | 归一 clean-room v1 | CLEANROOM_IMPLEMENTED | newow_composite_decision_cleanroom_v1 | packages/quant-core/guiyi_quant/newow/composite_decision.py::calculate_cleanroom_composite_decision | 只重分类周空日多，保留 page_difference_reason | 独立类型与身份，不覆盖页面事实 | 公式 Gate 已关闭 |
| 确定性评分与仓位矩阵 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_composite_decision_page_v3_2_82 | packages/quant-core/guiyi_quant/newow/composite_decision.py::calculate_composite_decision | 13 格 action token 与 Decimal 仓位区间；3/5/10/20 方向分与 60/85 封顶测试 | 只作研究观察映射 | 前后端精确合同 Gate 已关闭 |
| 日线波动率解释 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_composite_decision_page_v3_2_82 | packages/quant-core/guiyi_quant/newow/composite_decision.py::calculate_composite_volatility | gap TR、最近 20 个 TR、half-up 及 1.95/2.0/3.95/4.0 边界 | completed D1 同 owner segment 失败关闭 | 公式 Gate 已关闭 |
| 第一行动原则 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_first_action_principle_page_v3_2_63 | packages/quant-core/guiyi_quant/newow/composite_decision.py::calculate_first_action_principle | 页面优先级与 6 个股真实输出；只输出自有 token，不复制建议文案 | 研究观察解释，非订单 | 公式 Gate 已关闭 |
| AI 周日 16 组合矩阵 | stock_detail.html v3.2.63 | CLEANROOM_IMPLEMENTED | newow_ai_week_day_16_matrix_page_v1 token projection | packages/quant-core/guiyi_quant/newow/diagnostic_rules.py::diagnostic_tokens | 当前 16 周日组合全部 token 分支测试 | 只作解释 token | 公式 Gate 已关闭 |
| AI 六组合历史评分 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_ai_six_combo_page_v3_2_50 | packages/quant-core/guiyi_quant/newow/diagnostic_rules.py::rank_page_ai_combinations | 周/日/60m × 震荡/趋势；收益/Calmar/胜率、样本惩罚和稳定排序回归 | trustworthy_for_research=false，与 Walk-forward 返回类型隔离 | 不可信边界 Gate 已关闭 |
| AI 诊股 A-E 旧模板 | stock_detail.html v3.2.63 | REJECTED | legacy_ai_template_a_e_page_v1 | none | 含月线条件，只作历史页面事实 | 正式周期无月线，不带入 1w/1d/60m Core | 有证据的边界排除 |
| AI 诊断当前输出 | stock_detail.html v3.2.63 | CLEANROOM_IMPLEMENTED | newow_diagnostic_facts_cleanroom_v1 + newow_diagnostic_rules_cleanroom_v1 | packages/quant-core/guiyi_quant/newow/diagnostic_facts.py；diagnostic_rules.py | 27/27 页面输出只作来源；Core 仅输出事实和 token，不复制自由文案 | 同 owner segment、strict-before EMA20、换月重置 | 公式 Gate 已关闭 |
| 技术选股名称与返回阶段关系 | screener.html v3.2.82 black-box responses | BEHAVIOR_INFERRED | server-private phase semantics | packages/quant-core/guiyi_quant/newow/screener_observation.py | 单截面可排除“名称等于当根事件”的简单解释，但不能唯一识别完整规则 | 不迁移 | 等待第二个不同交易日或历史 as_of 的真实全量截面 |
| 技术选股 trend_build | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private trend_build behavior | none | 完整 2 页 40 行时点观察 | 不迁移 | 第二真实独立截面前保持 UNKNOWN |
| 技术选股 mainrise_build | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private mainrise_build behavior | none | 完整 1 页 3 行时点观察 | 不迁移 | 第二真实独立截面前保持 UNKNOWN |
| 技术选股 cup_handle | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private cup_handle behavior | none | 完整 2 页 27 行时点观察 | 不迁移 | 第二真实独立截面前保持 UNKNOWN |
| 技术选股 daily_buy | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private daily_buy behavior | none | 完整 2 页 21 行时点观察 | 不迁移 | 第二真实独立截面前保持 UNKNOWN |
| 技术选股 weekly_buy | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private weekly_buy behavior | none | 完整 2 页 21 行时点观察 | 不迁移 | 第二真实独立截面前保持 UNKNOWN |
| 技术选股 oscillation_build | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private oscillation_build behavior | none | 完整 1 页 1 行且信号字段缺失 | 不迁移 | 第二真实独立截面前保持 UNKNOWN |
| 归一趋势建仓 candidate | 归一 clean-room v1 | CLEANROOM_IMPLEMENTED | newow_trend_build_candidate_v1 | packages/quant-core/guiyi_quant/newow/screener_observation.py::evaluate_trend_build_candidate | 同段黄带且最新 BUILD 晚于 CLEAR | 只处理传入 facts，page_parity=false | 服务端 page-exact 仍 UNKNOWN |
| 归一主升浪建仓 candidate | 归一 clean-room v1 | CLEANROOM_IMPLEMENTED | newow_mainrise_build_candidate_v1 | packages/quant-core/guiyi_quant/newow/screener_observation.py::evaluate_mainrise_build_candidate | 同段主升浪持有且最新 BUILD 晚于 CLEAR | 只处理传入 facts，page_parity=false | 服务端 page-exact 仍 UNKNOWN |
| 归一杯柄 candidate | 归一 clean-room v1 | CLEANROOM_IMPLEMENTED | newow_cup_handle_candidate_v1 | packages/quant-core/guiyi_quant/newow/screener_observation.py::evaluate_cup_handle_candidate | READY/BREAKOUT 且无 hard failure | 只处理传入 facts，page_parity=false | 服务端 page-exact 仍 UNKNOWN |
| 真实 actual-dominant 数据链 | Catalog/MainContractMap/Canonical 2026-09-04 只读快照 | REPRODUCED_EXACT | newow_futures_actual_dominant_validation_v1 | services/quant-api/app/market_data/newow/futures_validation.py；trend_detail_service.py | 不使用股票收益外推 | rb/sc/m × 1d/1w/60m 为 9/9 series passed；rb/m 各 6 次换月，sc 24 次 | SC2302 W1 owner 子集反例已关闭 |
| 真实 OOS 与成本压力 | RQData historical commission/tick/limit snapshot 2026-09-04 | BEHAVIOR_INFERRED | newow_fixed_formula_walk_forward_v1 | packages/quant-core/guiyi_quant/newow/research_walk_forward.py | 不适用 | 27 单元中 18 个 1d/60m passed，9 个 1w 因 `NEWOW_WEEKLY_EXECUTION_LIMIT_CONTRACT_INSUFFICIENT` blocked | 只待周 K 输入与 next-open 执行日 limit 分离合同；禁止晋升收益结论 |
| 账户、自选、盯盘、订阅与分享 | 需用户私有状态 | UNKNOWN | none | none | 未采集且不触发 | 不适用 | 永久边界，除非用户另行明确授权 |
| 基本面、CANSLIM 与大师选股 | screener.html public UI only | UNKNOWN | none | none | 仅有页面阈值描述，无权威数据源合同 | 不扩建 A 股基本面平台 | 保留文档研究，不实现 |

## 采集与结论边界

- 证据采用匿名公开读取，没有 Cookie、Token、账号、关注、盯盘、订阅或分享操作。
- 2026-09-04 13:53 的 `trend_build` 先导请求为 39 行，13:57 完整分页时为 40 行；筛选数量是动态截面，不能当作公式常量。
- 页面浏览器实际使用 `www.v8848.cn/api/kline`。确认其为页面自身的公开匿名 GET 后，本 Slice 将只读捕获范围最小扩展到该精确路径；27 个页面点均冻结各自实际响应与 SHA-256，不含 Cookie、Token 或私有请求头。此前同 host K 线响应只作交叉核对。
- 所有股票证据都只是牛哇页面行为依据；所有期货迁移必须继续满足 completed bar、actual_dominant owner segment、next-open、成本、rollover 与 OOS/Walk-forward Gate。
- 本 Slice 不修改 Alert、Runtime、Scope、Canonical、RQData、PostgreSQL、Redis 或订单能力。
