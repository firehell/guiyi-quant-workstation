# RS 周线逐品种验收（候选，不含发布）

- 代码：`develop@ba986e588f617575b68511669029454107404d97`；完整周截点 `2026-09-18T07:00:00.000001Z`。
- Owner 授权精确 RS 批次 SHA `c1acf23ba52b0ad9551425f6878874ce9fcaaceb49c5c952d685769e8907e7de`；单次 apply 返回 `committed`。独立只读读回：64/64 新 Catalog 指针、133 根目标 W1 更新、同月 118 根非目标 W1 不变，D1 active 前像不变、旧 W1 文件保留；新 RS revision `6835f891a47bd9d813d25d29170d2f39707007145947b04ec6f1b6b10e9af2ae`，MDS W1-D1 v2 质量读回通过。RQData 请求 0。
- 真实 Catalog 三策略候选 readiness `audited/complete`，表示审计完成：趋势与主升浪 chart/reference `READY`；震荡 chart/reference 因合法来源质量中断 `WARMING`。四个辅助图层当前预热；震荡比较器 `UNAVAILABLE / INSUFFICIENT_BARS`，另两策略比较器不适用。不得计 RS 三策略全 READY。
- 正式 v14 代码 Scope 为 52/60，`rs` 使用 W1 输入质量 v2，其余 8 品种仍关闭；已推送 develop，尚未 Release 或 Runtime。只读正式 API smoke 对三策略各 chart/reference/MACD/comparator 共 12 项返回 HTTP 200 且状态与上项一致；PF 正式 W1 仍 409。
- 隔离真实浏览器在同一提交 `ba986e588`、同一截点完成 RS 三策略首次导航；震荡参考交易点击后明确显示“来源价格不可用后，当前策略参考正在重新预热”，保留历史有效记录。截图 `output/playwright/rs-weekly-v14-oscillation-reference-20260924.png`。Console 2 errors 均为隔离预览按合同拒绝 `/reference-trading/streams` 的 403，不是 Newow chart/reference 失败。候选 API/Web 进程已关闭。
- 验证：后端 247 passed，Web 68 passed，Web build、ruff、OpenSpec strict、`git diff --check` 均通过；独立 Review 无 Confirmed Issue。
- 现场 Runtime 仍为 v1.10.30、正式 v12/50；RS 的 develop v14/52 不能记为已发布或 Runtime Ready。按 Owner 意图，待其余品种逐项完成后再准备统一发布。
