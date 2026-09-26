# PL 周线逐品种验收（2026-09-24）

- 固定截点 `2026-09-18T07:00:00.000001Z`。写前 PL Catalog revision `51359328d8116ee39ff8efbdc8d7110512e3d8d736c3c935524f1bd956f50216`；7 个物理合约，其中 PL2604 没有已归属的完整周，5 个合约共 63 根缺周有完整 D1、5 根成交额冲突有成功 D1 回执，89 根合法质量中断。
- 精确包 SHA-256 `cc8f45f93f7110e26847e13fb78580e622e0eb0afd6fae92bb51822ba40ee36e`：24 个 W1 月分区（19 新、5 旧），68 根目标周。RQData 请求与 D1 写入均为 0。dry-run、24/24 旧指针检查、只读候选 MDS 叠加回读、独立 Review 均通过。正式提交一次，24/24 新指针和质量回读通过。写后 Catalog revision `2b83eab0d0d4368db261c55f28d66c01ddb5496c2a4d2f64d9fd7c648eeb9cf0`；刷新盘点只有 89 根已证实质量中断。
- Candidate readiness：趋势、震荡、主升浪主视图、图表、参考交易均 READY；主力控盘 READY，MACD、涨跌动能、照妖镜 WARMING，震荡比较器 UNAVAILABLE，其他比较器 NOT_APPLICABLE。没有改价或降低校验阈值。
- 正式候选 Scope v17：`develop@6ea7e3faf9a6cf2f137cf127e62dafad205236b0`，55/60，剩余 PR/PX/SF/SH/SM。后端相关 188 passed，Web 全部 679 passed、1 skipped，Web build、ruff、目标 OpenSpec strict、diff check 和独立 Review 通过。全量 OpenSpec 因本次未改 `reference-trading/spec.md` 的两处结构错误失败。正式只读 API smoke：三策略各图表、参考交易、MACD、比较器共 12 个 HTTP 200 且状态符合预期，PR 周线仍 409。
- 隔离真实浏览器在同一 commit、同一截点完成三策略首次导航：趋势 HOLD、震荡 FLAT、主升浪 HOLD，周线图、辅助状态、参考交易统计均加载；主升浪截图 `output/playwright/pl-weekly-v17-main-rise-20260924.png`。顶部独立报价不可用和当前主力不可判定不等于周线图失败。隔离预览按合同拒绝 `/reference-trading/streams` 的 403。预览进程已关闭。
- Release 和 Runtime promotion 尚未执行。
