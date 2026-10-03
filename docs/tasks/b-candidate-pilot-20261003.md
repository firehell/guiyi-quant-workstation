# B 豆二历史页面候选

状态：**证据已齐，待普通合入 develop**。只处理 B。窗口 2023-01-01..2026-09-24，`as_of=2026-09-24T07:00:00.000001+00:00`。Canonical 1m 只作聚合源。候选页面为 5m/15m/30m/60m × trend/oscillation/dual，并查看 D1/W1 六场。候选保持 `enabled=false`、`activation_generation=0`、`complete_window_proven=false`。正式分钟开放、Runtime、Scope、通知和交易未改。

资格在 `b73b5d9c587a9d99165393c21c784cd0747b2ae0`，API 单品种预览集合和页面 v27 白名单一起提交。原始证据在 `.worktrees/b-candidate-pilot/outputs/b-candidate-pilot-20261003/`，成功页面采集在 `page-capture-open/`，不进入 Git。第一次采集停在 `page-capture/`：浏览器会话尚未 `open`，首场 `SCENE_INVOCATION_FAILED_NO_REPLAY`，没有成功前缀，不能 `--resume-from`。打开 `b-candidate` 会话后在新目录采完。

27 个物理 owner、108 个维护单元一次完成：268 次真实 RQData 请求、1072 个派生月。B2611 四频为 NO_GAP。无重入、无 ArrowInvalid、无失败重试。计划 SHA `eb16e00c9158228b3fcd5fddd66ff3a737c5fd57b2a64fb437a4b3262b801330`。整包保守估算高于当日剩余额度，单单元最大估算 76400640 字节仍低于剩余额度，因此按单元门继续；完成后账户已用 23473877 / 1073741824 字节。8 条基础流和 4 条融合流均为首次构建，写后读回 READY，且未启用。四频基础覆盖均为 FULL、27 个 owner。独立只读复核用同一物理 1m 和 Session 重算已发布分区，四频全部 PASS：5m 416325、15m 138775、30m 72432、60m 42305。资产计划输入计数比已发布分区多 26 根，已发布分区与重算结果逐根相等。

API 12/12 READY，矩阵 152 次 HTTP 200。预检为现场 GET。Chrome 19/19 场、49 张原图（1280×720）；`evidence-index.json` 为 PASS，离线审计为 `NUMERICAL_PASS_VISUAL_PENDING`。已查看全部 12 张分钟主图、6 张日周主图、取消场，以及 5m 趋势曲线/较早窗口、15m 趋势较早窗口、60m 趋势较早窗口、60m 双策略曲线和 W1 震荡曲线。主图、成交量和 MACD 都画出来了。页头在含顶栏的画面上显示目标价和吸筹价。保留的展示限制：标记标签重叠、tooltip 压住右侧价格轴、较早窗口标签挤出可视区、趋势转折副图在放大后只占左侧短段、持有过程不可用。W1 趋势转折当前段 44/120 根 Bar 仍在预热。W1 震荡全窗口只有 1 笔 CLOSED（+6.34%），不能当成可执行结果。60m 双策略曲线与资产读回一致：559 笔、胜率 75.3%、累计 +317.7%，这是零费零滑点页面参考。5m 趋势全窗口页面为 5406 笔、胜率 65.22%、累计 +835.02%。

收益都是 `page_parity=true`、`executable=false`。没有把融合选择状态机完整重放，也没有把取消场的返程卡片逐张身份或自然 TTL 写成已证明。不计入原 13/21 分母。
