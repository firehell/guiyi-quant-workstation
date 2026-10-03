# BZ 纯苯历史页面候选

状态：**证据已齐，待普通合入 develop**。只处理 BZ。权威上市日是 2025-07-08，窗口因此是 2025-07-08..2026-09-24，`as_of=2026-09-24T07:00:00.000001+00:00`。Canonical 1m 只作聚合源。候选页面为 5m/15m/30m/60m × trend/oscillation/dual，并查看 D1/W1 六场。候选保持 `enabled=false`、`activation_generation=0`、`complete_window_proven=false`。正式分钟开放、Runtime、Scope、通知和交易未改。

资格在 `9d8d3507bdbd1e5da5abd3245c8777f87f245d37`，API 单品种预览集合和页面 v27 白名单一起提交。原始证据在 `.worktrees/bz-candidate-pilot/outputs/bz-candidate-pilot-20261003/`，页面采集在 `page-capture/`，不进入 Git。

8 个物理 owner（BZ2603..BZ2610）、32 个维护单元一次完成。1m 已在库，真实 RQData 请求 0 次，派生月 60 个。无重入、无 ArrowInvalid、无失败重试。计划 SHA `28f128b98749c1b29e2b62775f128e0c0950cd06c6e2aae7f48ccb3b4e5344b3`。8 条基础流和 4 条融合流均为首次构建，写后读回 READY，且未启用。趋势覆盖 FULL、8 个 owner。震荡覆盖 PARTIAL：上市当日 2025-07-08 为 WARMING，其后区间 VALID。独立只读复核用同一物理 1m 和 Session 重算已发布分区，四频全部 PASS：5m 109185、15m 36395、30m 18996、60m 11095。

API 12/12 READY，矩阵 152 次 HTTP 200。预检为现场 GET。Chrome 19/19 场、49 张原图；`evidence-index.json` 为 PASS，离线审计为 `NUMERICAL_PASS_VISUAL_PENDING`。已查看全部 12 张分钟主图、6 张日周主图、取消场，以及 5m 趋势较早窗口、60m 双策略曲线和 W1 震荡曲线。主图、成交量和 MACD 都画出来了。页头显示目标价和吸筹价。保留的展示限制：标记标签重叠、tooltip 压住右侧价格轴、较早窗口的趋势转折只占左侧短段、持有过程不可用。W1 趋势转折当前段 27/120 根 Bar 仍在预热。W1 震荡全窗口 1 笔 CLOSED（-1.29%，胜率 0%），页面写明历史覆盖不完整，不能当成可执行结果。60m 双策略曲线与资产读回一致：168 笔、胜率 79.2%、累计 +218.04%，这是零费零滑点页面参考。

收益都是 `page_parity=true`、`executable=false`。不计入原 13/21 分母。
