# PR 周线逐品种验收（2026-09-24）

- 固定截点 `2026-09-18T07:00:00.000001Z`。写前 PR Catalog revision `8f11e98bc3126094b8beb3e0b755296ff4799986f2959acccbc1cc4b48797902`；16 个物理合约，其中 14 个有修复目标：389 根完整 D1 对应缺周、19 根旧无交易聚合、12 根有 D1 成功回执的成交额冲突；106 根合法质量中断。
- 精确包 SHA-256 `bdd48032f2644d31d00cabfbd68fa87f8e04a60e393d2ae6257008f8aee0ebb5`：122 个 W1 月分区、420 根目标周。RQData 请求与 D1 写入均为 0。dry-run、122/122 旧指针检查、只读候选 MDS 叠加回读、独立 Review 均通过。正式提交一次，122/122 新指针与质量回读通过。写后 Catalog revision `6604a403e5eb0156d41a51e40086b4c6adf4bfe04b88db3d5bed6f2add52e298`；刷新盘点只剩 106 根合法质量中断。
- Candidate readiness：趋势、震荡、主升浪主视图、图表、参考交易均 READY；主力控盘与涨跌动能 READY，MACD 与照妖镜 WARMING；震荡比较器 UNAVAILABLE，其他比较器 NOT_APPLICABLE。未制造价格或降低阈值。
- 正式候选 Scope v18：`develop@d43a547d059cc1e62e355244a37550d9b4bd7879`，56/60，剩余 PX/SF/SH/SM。后端相关 189 passed，Web 全部 680 passed、1 skipped，Web build、ruff、目标 OpenSpec strict、diff check 和独立 Review 通过。全量 OpenSpec 仍被未改 `reference-trading/spec.md` 的两处结构错误阻挡。正式只读 API smoke：三策略各图表、参考交易、MACD、比较器共 12 个 HTTP 200 且状态符合预期，PX 周线仍 409。
- 隔离真实浏览器在同一 commit、同一截点完成三策略首次导航：趋势 HOLD、震荡 FLAT、主升浪 HOLD，周线图、辅助状态、参考交易统计均加载；主升浪截图 `output/playwright/pr-weekly-v18-main-rise-20260924.png`。独立报价不可用和当前主力不可判定不等于周线策略失败；隔离预览按合同拒绝 `/reference-trading/streams` 的 403。预览进程已关闭。
- Release 和 Runtime promotion 尚未执行。
