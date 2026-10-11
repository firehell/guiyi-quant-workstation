# 牛哇两个 P0 页面一致性修正（2026-10-09）

## 范围与结果

用户交办已有趋势、震荡、主升浪及融合的两个 P0；不增加测试/测试2/测试3/测试4，不涉及推送、选股、下载、资产重建、发布或 Runtime 切换。

从 develop `fdc818f70` 复用历史 P0 修正，随后接入 develop 的消息功能提交 `22362d4f4` 和完整首页卡片提交 `49ff8a802`。历史任务 `newow-p0-v3379-20261008.md` 中 720 项候选验收和宿主阻断是旧证据，本次没有执行该阶段，也没有将其视作完成。

## 修正

- 趋势补齐初始无入场 CLEAR；震荡主图清仓当根不再次建仓。数值边界采用公开 JS 的顺序与 binary64 运算，避免阈值附近 Marker 漂移。
- 普通值、理论值及主图信号保持独立口径。主升浪理论 Close 入场并排除清仓当根峰值；震荡 HHV 保留原站滚动窗口；融合理论排除清仓当根 High。
- 采用公开页面日期窗口、加法累计和对应回撤算法；末根页面估值不修改 ReferenceTrade OPEN 事实。
- 跨合约聚合排除窗口开始前已结束的 owner，避免原站单段“日期无匹配返回全部”在旧合约上污染近一年。完整输入仍无开始日期匹配时保留原站回退；warm-up 不充当有效观测证据。
- 理论模式标明“单笔最大亏损”，并说明原站日期窗口会重算曲线回撤；修正统计布局与长曲线 extrema 的参数栈溢出。

版本：`newow_product_detail_v4`、`newow_marker_reference_zero_cost_v4`、趋势 `newow_trend_band_page_v3`、震荡 page v2、fusion v2、页面收益 `newow_page_performance_v3379_v2`。旧分钟资产不能冒充这些新身份。

## 实际验证

测试使用主仓库既有 Python/Node 依赖，不安装新依赖。

- Python Newow + reference_trading + P0 工具完整回归：3557 passed / 53 skipped；两个 socket 测试受 sandbox bind 限制，宿主重跑 2 passed。该完整回归发生在最后窗口修正前。
- 最终窗口修正后：页面收益、adapter、product/API、数值及原 JS oracle 定向回归 217 passed；独立复核再跑 64 passed，无 Confirmed Issue，允许集成 develop。
- `node --test tests/*.test.ts`：827 passed / 1 skipped / 0 failed；`npm run build` 类型检查、Vite 构建及包依赖检查通过。
- OpenSpec 验证 10 passed；定向 ruff、`git diff --check` 通过。
- 原公开 JS oracle 与冻结的 A 5m 实际输入逐值比较：19 owner，RAW_SOURCE_PARITY_ONLY 通过。冻结输入不能代表 60 品种/720 项候选已验收。
- 本地只读 HTTP：RB D1 三策略及融合均 200；2025-09-24 至 2026-09-24 的所有曲线日期与退出交易均在窗口内，schema/projection 身份一致。Chrome 实页近一年与普通/理论切换通过，最终截图位于主仓库 `outputs/newow-p0-current-20261009/`。

HTTP 初次失败来自预览环境 DB/Canonical 路径绑定；仅临时进程使用既有正确数据根和只读数据库配置，没有修改持久配置或修补数据。最终 60m 返回 `NOT_BUILT`：新版本参考资产尚未构建，不能宣称分钟全品种页面已验收。

## 交付边界

代码集成不等于发布或 Runtime Ready。未运行候选重建，不启用推送、不操作账户。下一步仅为按新身份构建并验收分钟参考资产；本任务保留为后续工作。

集成检查曾发现 `22362d4f4` 引用未提交卡片组件及第三参数路由；随后首页任务提交完整 `49ff8a802`，本任务接入该提交并保留完整卡片和消息功能。临时撤接线与测试 loader 补充均撤回，没有作为交付修改。主工作区其他未提交修改保持原样。

最终集成回归（含49ff首页卡片）：Python479 passed；Web835 passed/1 skipped；类型与构建通过。接入后续 `773cb7a12` 发布记录时，只需合并同一条旧断言的双重验证：保留“查看依据”已移除检查与实际 explain-main 事件检查。P0 本身仍未发布。

代码已随 `364f99dd5` 快进集成并普通推送 develop；最终合并后定向81 passed、全差异secret scan findings=0。仅更新候选状态，没有改写既有发布/Runtime身份。
