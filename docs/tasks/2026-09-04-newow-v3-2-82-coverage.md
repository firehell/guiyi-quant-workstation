# 牛哇 v3.2.82 功能覆盖与复刻状态

状态：`SLICE_A_EVIDENCE_FROZEN`

本表把页面观察、手册主张、归一实现和期货迁移证据分开。唯一状态集为 `OBSERVED_EXACT`、`REPRODUCED_EXACT`、`BEHAVIOR_INFERRED`、`CLEANROOM_IMPLEMENTED`、`UNKNOWN`、`REJECTED`。其中推断不能冒充页面公式；`UNKNOWN` 与 `REJECTED` 均没有实现入口。

外部证据根：`newow-strategy-detail-research/v3.2.82-gap-closure`
证据清单 SHA-256：`8e1c25fb08a9c7da37fd8ce218cc1ecaa24582c745a9fb1943d8aef5f6c44c2c`

| Feature | Current source/version | Evidence status | Formula identity | Implementation entry | Stock evidence | Futures evidence | Remaining gate |
|---|---|---|---|---|---|---|---|
| 首页功能与策略入口 | index.html v3.2.82 | OBSERVED_EXACT | page navigation and legacy filters | none | 首页匿名截图与静态源码 | 不适用 | Slice D 核对命名策略行为 |
| 股票详情页与多周期切换 | stock_detail.html static v3.2.63 under v3.2.82 site | OBSERVED_EXACT | page detail orchestration | none | 3 指数加 6 股票，week/day/60min 共 27 点 | 不适用 | Slice E 接入期货详情页 |
| S跑与 D1-D3 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_escape_d123_page_v2 | packages/quant-core/guiyi_quant/newow/escape_d123.py | 9 标的旧金样本逐值 exact | actual_dominant D1 研究测试已存在 | Slice D 补 D4-D6 组合解释 |
| D4-D6 建仓标记 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_buy_d456_page_v1 | packages/quant-core/guiyi_quant/newow/main_rise.py | 9 标的旧金样本逐值 exact | actual_dominant D1 研究测试已存在 | Slice D 纳入诊断输出 |
| 趋势黄蓝带 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_trend_band_page_v2 | packages/quant-core/guiyi_quant/newow/trend_band.py | 3 指数加 6 股票旧金样本 exact；v3.2.82 27 点回归 | actual_dominant D1 已有 owner-segment 合同 | Slice E 组合输出接入 |
| 震荡策略 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_oscillation_hhv_llv10_page_v1 | packages/quant-core/guiyi_quant/newow/oscillation_channel.py | 9 标的旧金样本 HHV10/LLV10 与状态 exact | 因果 next-open 研究入口已存在 | Slice E 组合输出接入 |
| 主升浪 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_main_rise_ma35_ma45_page_v1 | packages/quant-core/guiyi_quant/newow/main_rise.py | 9 标的旧金样本 MA35/MA45、J、信号 exact | 因果 next-open 研究入口已存在 | Slice D 补行为候选层 |
| 杯柄形态 primitive | 手册加详情页 v3.2.63 | CLEANROOM_IMPLEMENTED | newow_cup_handle_v1 | packages/quant-core/guiyi_quant/newow/cup_handle.py | 股票形态样本和 causality 测试已有 | actual_dominant D1 研究 primitive 已有 | 不能宣称当前服务端 cup_handle 筛选 exact |
| 11 周期 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_magic11_page_v1 | packages/quant-core/guiyi_quant/newow/magic11.py | 516 markers 与 3240 count lines exact | 主升浪组合内可复算 | Slice D 纳入诊断模板 |
| 主力控盘副图 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_main_force_control_page_v1 | packages/quant-core/guiyi_quant/newow/subplots.py | 9 标的数值与状态 exact | 研究 primitive 可复算 | Slice D 纳入诊断模板 |
| 照妖镜副图 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_zhaoyao_mirror_repainting_page_v1 | packages/quant-core/guiyi_quant/newow/subplots.py | 9 标的逐值 exact | repainting，只允许研究解释 | Slice D 明示重绘边界 |
| 涨跌动能副图 | stock_detail.html v3.2.63 | REPRODUCED_EXACT | newow_up_down_energy_page_v1 | packages/quant-core/guiyi_quant/newow/subplots.py | 9 标的逐值 exact | 研究 primitive 可复算 | Slice D 纳入诊断模板 |
| 目标价与吸筹价原始通道 | strategy-calc.js v1.0.9, query v3.2.82 | CLEANROOM_IMPLEMENTED | newow_target_absorb_hhv_llv10_page_v1 | packages/quant-core/guiyi_quant/newow/price_channel.py::calculate_price_channel | v3.2.82 的 27/27 页面末值与 HHV10/LLV10 一致 | 单段 actual_dominant 输入可复算 | Slice B 因果比较器与期货验证 |
| 目标价与吸筹价展示选择 | strategy-calc.js v1.0.9, query v3.2.82 | CLEANROOM_IMPLEMENTED | newow_target_absorb_display_selection_page_v1 | packages/quant-core/guiyi_quant/newow/price_channel.py::select_display_prices | 日周状态、突破升级、fallback、昨收 clamp 与分支 token 测试 | 不进入期货信号 | Slice B Review |
| 参数比较器页面口径 | stock_detail.html v3.2.63 | CLEANROOM_IMPLEMENTED | newow_hhv_llv_window_optimizer_page_v1 | packages/quant-core/guiyi_quant/newow/price_channel.py::rank_page_channel_windows | 601 根页面响应离线 JS oracle，五窗口逐字段与排名 parity | `trustworthy_for_research=false`，禁止晋升 | Slice B 与 causal-research 身份隔离 |
| 参数比较器因果研究口径 | 归一设计 v1 | BEHAVIOR_INFERRED | newow_channel_window_compare_causal_v1 | none | 页面偏差的 clean-room 修正设计，不宣称页面公式 | 需要 next-open、成本、rollover、prefix 合同 | Slice B TDD 实现并保留研究边界 |
| 页面同 Bar 无成本比较器直接晋升可信策略 | stock_detail.html v3.2.63 | REJECTED | none | none | 页面执行时序和无成本口径已冻结 | 不迁移 | 因违反因果与成本边界而永久拒绝；只允许另建 causal-research 身份 |
| 综合决策 13 格矩阵 | stock_detail.html v3.2.63 | OBSERVED_EXACT | newow_composite_decision_page_v1 | none | 13 branch keys 与 27 个非占位页面输出 | 尚未实现 | Slice C page-exact 与 corrected 分身份 |
| 确定性评分与仓位矩阵 | stock_detail.html v3.2.63 | OBSERVED_EXACT | newow_composite_certainty_page_v1 | none | 27 个页面分数、决策与仓位文本 | 尚未实现 | Slice C 枚举全状态空间 |
| 日线波动率解释 | stock_detail.html v3.2.63 | OBSERVED_EXACT | newow_daily_atr20_volatility_page_v1 | none | 27 个页面波动率输出 | 尚未实现 | Slice C ATR 边界与缺失数据测试 |
| 第一行动原则 | stock_detail.html v3.2.63 | OBSERVED_EXACT | newow_first_action_principle_page_v1 | none | 页面控制流和 27 个真实输出 | 尚未实现 | Slice C 验证周空日多风险分支 |
| AI 六组合矩阵 | stock_detail.html v3.2.63 | OBSERVED_EXACT | newow_ai_week_day_16_matrix_page_v1 | none | 当前 16 周日组合源码事实 | 尚未实现 | Slice D token 化实现，不复制长文案 |
| AI 诊股 A-E 旧模板 | stock_detail.html v3.2.63 | OBSERVED_EXACT | legacy_ai_template_a_e_page_v1 | none | 含月线条件，只作历史页面事实 | 不带入 1w/1d/60m Core | Slice D 只保留来源映射 |
| AI 诊断当前输出 | stock_detail.html v3.2.63 | OBSERVED_EXACT | newow_diagnostic_tokens_page_v1 | none | 27/27 非占位诊断，保留输入与输出 token | 尚未实现 | Slice D 做确定性模板而非自由文本复制 |
| 技术选股 trend_build | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private trend_build behavior | none | 完整 2 页 40 行时点观察 | 不迁移 | Slice D 第二截面与 primitive 交集反推 |
| 技术选股 mainrise_build | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private mainrise_build behavior | none | 完整 1 页 3 行时点观察 | 不迁移 | Slice D 第二截面与主升浪 primitive 反推 |
| 技术选股 cup_handle | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private cup_handle behavior | none | 完整 2 页 27 行时点观察 | 不迁移 | Slice D 不把旧首页过滤器冒充新公式 |
| 技术选股 daily_buy | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private daily_buy behavior | none | 完整 2 页 21 行时点观察 | 不迁移 | Slice D 第二截面与趋势状态反推 |
| 技术选股 weekly_buy | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private weekly_buy behavior | none | 完整 2 页 21 行时点观察 | 不迁移 | Slice D 第二截面与趋势状态反推 |
| 技术选股 oscillation_build | screener.html v3.2.82, server response 2026-09-04 | UNKNOWN | server-private oscillation_build behavior | none | 完整 1 页 1 行且信号字段缺失 | 不迁移 | Slice D 第二截面与震荡状态反推 |
| 账户、自选、盯盘、订阅与分享 | 需用户私有状态 | UNKNOWN | none | none | 未采集且不触发 | 不适用 | 永久边界，除非用户另行明确授权 |
| 基本面、CANSLIM 与大师选股 | screener.html public UI only | UNKNOWN | none | none | 仅有页面阈值描述，无权威数据源合同 | 不扩建 A 股基本面平台 | 保留文档研究，不实现 |

## 采集与结论边界

- 证据采用匿名公开读取，没有 Cookie、Token、账号、关注、盯盘、订阅或分享操作。
- 2026-09-04 13:53 的 `trend_build` 先导请求为 39 行，13:57 完整分页时为 40 行；筛选数量是动态截面，不能当作公式常量。
- 页面浏览器实际使用 `www.v8848.cn/api/kline`。确认其为页面自身的公开匿名 GET 后，本 Slice 将只读捕获范围最小扩展到该精确路径；27 个页面点均冻结各自实际响应与 SHA-256，不含 Cookie、Token 或私有请求头。此前同 host K 线响应只作交叉核对。
- 所有股票证据都只是牛哇页面行为依据；所有期货迁移必须继续满足 completed bar、actual_dominant owner segment、next-open、成本、rollover 与 OOS/Walk-forward Gate。
- 本 Slice 不修改 Alert、Runtime、Scope、Canonical、RQData、PostgreSQL、Redis 或订单能力。
