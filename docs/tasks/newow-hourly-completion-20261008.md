# 牛哇60m完整功能与60品种发布

用户明确交办实现、develop集成、minor发布及正式运行树切换。范围固定截至2026-09-24T07:00:00.000001Z；不重跑已闭环分钟维护。1m页面、分钟主升浪、持续分钟更新及reference worker保持关闭，不新增通知、受众或交易。承接v1.12.1：苏冰只保存信号/Event，HTDY既有通知保持，auto_order=false。

## 候选实现和验证

- capability v31正式纳入PP，60品种四分钟周期趋势/震荡/双策略；AI response v2返回W1/D1/60m六组合，窗口起点分别2024-06-01、2025-09-01、2026-04-01。
- opt-in CDV2统一历史as_of，小时趋势/震荡事实、计龄、原权重、方向/确定性评分和第一行动原则参与；缺失/预热/异owner显式不可用。分钟不调用MAIN_RISE，J风险不以日周替代。
- 同合约60m当前Close与D1/W1通道目标/吸筹展示；日周路径仍为背景，杯柄仅D1。震荡状态卡采用27格三周期解释；版本guiyi_newow_status_card_hourly_v2，独立于策略状态与CDV2仓位参考强度。
- AI采纳只切图表策略/周期；page-parity、段末参考估值、五窗口理论比较及账户事实独立。五窗口比较入口仅震荡显示，前端接受显式Canonical V1身份并继续拒绝跨频V2。

实际验证命令保存在本任务outputs/newow-hourly-20261008。最终后端限定风险范围pytest661 passed/1既有skip（reader/service/API/cache/CDV2/AI/cross-period/comparator/candidate-preview及工程一致性）；Newow Node测试390 passed；vue-tsc、Vite build与bundle topology通过，OpenSpec10通过，Ruff、uv offline lock、diff/secret通过。扩展全Newow测试因两个旧PP关闭断言失败后中断：756 passed/2failed，原日志保留；更新范围断言后完整运行受影响定向集合，不声称全Newow套件通过。

真实候选API：capability60/60，60品种×趋势/震荡小时决策120/120 HTTP200；240小时事实ready，4项日周预热/owner不足明确保留，每个源bar_end不晚于共同截止。PP四分钟周期×两基础图表8/8，均500bar，正式入口无preview扩权。Chrome真实读取PP60m综合决策/目标价/状态，六卡AI推荐60m，从D1采纳切60m，五窗口比较器与双策略依赖；报价不可用保持，不冒充Live行情。

## 源码与独立Review

原冻结四组合oracle保持不变。当前公开整页v3.3.79 SHA256 3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d；共享strategy-calc JS仍a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e。只独立提取scoreCombos（d9cb5044e8b797558a091f1647fe4bebc942729b822457a254eee0da1733d2c2）及历史AI_ADVICE_MATRIX（661da186d387bf553bc17b37bee5fbc1e1a5649a4b2312da4cb0704cb41e7ae6）；未采用新页面测试策略或新版决策语义，不把新整页称旧冻结源码。可重现入口tools/build_newow_hourly_oracle.mjs，4个case均6项，覆盖不足三笔、低样本、零回撤、稳定同分；27格逐值对照通过。

独立Review先发现小时颜色/推荐序号两P2、六组合oracle仍四项P1，均修复并复核；允许集成develop。真实比较器暴露V1前端身份拒绝，RED后修正并真实复验。旧OpenSpec要求段位置错误已修正。所有失败证据保留，未改数据或削弱评分。

## 发布与运行

当前待最后候选绑定、集成和发布运行证据。正式状态仍以STATUS.md及现场为准，不提前声明RELEASED或RUNTIME_READY。自然Live/盘后/weekly未发生或证据不足时继续待验收，不手工运行自然业务。
