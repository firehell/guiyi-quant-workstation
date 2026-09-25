# PX 周线逐品种验收（2026-09-24）

- 固定截点 `2026-09-18T07:00:00.000001Z`。写前 PX Catalog revision `6306a34eeac1e2854a556cfc2d98c42d1e08bc219967a797e72d71d216aba738`；13 个物理合约，PX2610 无已归属完整周；8 个合约有 214 根完整 D1 对应缺周、8 根旧无交易聚合、7 根有 D1 成功回执的成交额冲突，另有 33 根合法质量中断。
- 精确包 SHA-256 `a2ed6ec464c3c580b83a6ff38c313f96829dfe306e114643fc4235f3e9ed77e7`：67 个 W1 月分区（56 新、11 旧）、229 根目标周。RQData 请求和 D1 写入均为 0。dry-run、67/67 旧指针、只读候选 MDS 叠加回读及独立 Review 通过；正式提交一次且 67/67 新指针和质量回读通过。写后 Catalog revision `31d045dadd7f334775700142885fdf71a8c7fe49d5575f219321dbf34ffe25c8`；刷新盘点只剩 33 根合法质量中断。
- Candidate readiness：趋势、震荡、主升浪主视图、图表、参考交易均 READY；主力控盘、涨跌动能、照妖镜 READY，MACD WARMING；震荡比较器 UNAVAILABLE，其他比较器 NOT_APPLICABLE。未制造价格或放宽阈值。
- 正式候选 Scope v19：`develop@375da02b04903cc7b401c575305622e455efdd9e`，57/60，剩余 SF/SH/SM。后端相关 190 passed，Web 全部 681 passed、1 skipped，Web build、ruff、目标 OpenSpec strict、diff check 和独立 Review 通过。全量 OpenSpec 仍受未改 `reference-trading/spec.md` 的两处结构错误影响。正式只读 API smoke：三策略各图表、参考交易、MACD、比较器共 12 个 HTTP 200 且状态符合预期，SF 周线仍 409。
- 隔离真实浏览器在同一 commit、同一截点完成三策略首次导航：趋势 HOLD、震荡 FLAT、主升浪 HOLD，周线图、辅助状态、参考交易统计均加载；主升浪截图 `output/playwright/px-weekly-v19-main-rise-20260924.png`。顶部独立报价不可用和当前主力不可判定不等于周线策略失败。隔离预览按合同拒绝 `/reference-trading/streams` 的 403；进程已关闭。
- Release 和 Runtime promotion 尚未执行。
