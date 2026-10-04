# A 豆一历史页面候选

状态：**已普通合入 develop `99f6c89e5c51cc172f0540fcb11e740cee206c47`**。只处理 A。窗口 2023-01-01..2026-09-24，`as_of=2026-09-24T07:00:00.000001+00:00`。Canonical 1m 只作聚合源。候选页面为 5m/15m/30m/60m × trend/oscillation/dual，并查看 D1/W1 六场。候选保持 `enabled=false`、`activation_generation=0`、`complete_window_proven=false`。正式分钟开放、Runtime、Scope、通知和交易未改。

数据与资产冻结在 `0f3551c458e1f81add3d2f142331f8b7d9244294`。该提交只加了 API 单品种预览资格，页面能力白名单漏了 `a`，第一次 Chrome 采集停在「牛哇开放能力不可用」。白名单和对应 Web 测试补在 `0a0a36f16`，成功采集时预览页面已经按这份未提交源码打开；API 身份仍是前一个 SHA。原始证据在 `.worktrees/a-candidate-pilot/outputs/a-candidate-pilot-20261003/`，页面采集在其子目录 `page-capture/`，不进入 Git。失败的第一次采集留在父目录 `browser/`。

19 个物理 owner、76 个维护单元一次完成：80 次真实 RQData 请求、580 个派生月，无 ArrowInvalid，也没有失败重试。8 条基础流和 4 条融合流均为首次构建，写后读回 READY，且未启用。四频基础覆盖均为 FULL、19 个 owner。独立只读复核用同一物理 1m 和 Session 重算已发布分区，四频全部 PASS：5m 287712、15m 95904、30m 50056、60m 29236。

API 12/12 READY，矩阵 152 次 HTTP 200。预检为现场 GET。Chrome 19/19 场、49 张原图；`evidence-index.json` 为 PASS，离线审计为 `NUMERICAL_PASS_VISUAL_PENDING`。已查看全部 12 张分钟主图、6 张日周主图、取消场，以及 5m 趋势曲线/较早窗口、15m 趋势较早窗口、60m 趋势较早窗口、60m 双策略曲线和 W1 震荡曲线。主图、成交量和 MACD 都画出来了。保留的展示限制：标记标签重叠、tooltip 和顶栏遮挡、较早窗口标签挤出可视区、页头报价不可用、持有过程不可用。W1 趋势转折当前段 44/120 根 Bar 仍在预热。W1 震荡全窗口只有 1 笔 CLOSED（+5.3%），不能当成可执行结果。60m 双策略曲线与资产读回一致：548 笔、胜率 75.5%、累计 +229.21%，这是零费零滑点页面参考。

收益都是 `page_parity=true`、`executable=false`。没有把融合选择状态机完整重放，也没有把取消场的返程卡片逐张身份或自然 TTL 写成已证明。

## 2026-10-04 独立终验与打包

已补齐18个数值场景、19场49张原图逐张独立检查，22387笔CLOSED价格回报、22423个SVG点及651份索引文件通过。原生报告和采集失败保持，独立阶段报告SHA为`41cf9affad829c1925f55f1ae87609682b2fe547ee04e6859e5029bf4de6cb14`。

本品种4个当前来源窗口与12条禁用资产及融合依赖一致；正式v29的8份基础响应和4组融合结果，以及6次UTC/null/旧token409与fresh恢复补验通过。共同证据在本机`outputs/release-45-products-20261004/`，见[v1.11.1说明](../releases/v1.11.1.md)。共同融合恢复修复经两轴独审、776项Web测试和61项浏览器回归通过；真实PL60m闲置335.6秒后旧token409、一次原窗口重建及新token融合200已封存。190份UTC/null/拒绝原始响应独审通过。本品种现为CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12，纳入v1.11.1发布包；正式发布身份以STATUS.md实际读回为准。
