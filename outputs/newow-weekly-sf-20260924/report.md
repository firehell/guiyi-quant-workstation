# SF 周线逐品种验收（2026-09-24）

- 固定截点 `2026-09-18T07:00:00.000001Z`。写前 SF Catalog revision `fac3eec9b6cc12c08309493d6616b0080d2dd124c0c6383ef4b618a1e5de3b4b`；28 个物理合约、23 个修复合约，725 根完整 D1 对应缺周、33 根旧无交易聚合、18 根仅成交额冲突、SF2506/2025-04-11 一根成交量与成交额双字段冲突，10 根合法质量中断。19 根冲突均有当前 D1 成功回执。
- 精确包 SHA-256 `66d62ff60efcf2cc933e38bd4a5761f3311ff9273e9727f6dda674337b89a8d5`：211 个 W1 月分区（176 新、35 旧）、777 根目标周。RQData 请求和 D1 写入均为 0。dry-run、211/211 旧指针、只读候选 MDS 叠加回读及独立 Review 通过；正式提交一次且 211/211 新指针及质量回读通过。写后 Catalog revision `0dc50f8e2e0c80735c01f96f09b8144ac9f4343a421b7497f58917e31cb84bc1`；刷新盘点只剩 10 根合法质量中断。
- Candidate readiness：趋势、震荡、主升浪主视图、图表、参考交易和 MACD、主力控盘、涨跌动能、照妖镜均 READY；震荡比较器 UNAVAILABLE，其他比较器 NOT_APPLICABLE。未制造价格或放宽阈值。
- 正式候选 Scope v20：`develop@4010c0a847f95360f72301fada6856ecd6308a69`，58/60，剩余 SH/SM。后端相关 191 passed，Web 全部 682 passed、1 skipped，Web build、ruff、目标 OpenSpec strict、diff check 和独立 Review 通过。全量 OpenSpec 仍受未改 `reference-trading/spec.md` 的两处结构错误影响。正式只读 API smoke：三策略各图表、参考交易、MACD、比较器共 12 个 HTTP 200 且状态符合预期，SH 周线仍 409。
- 隔离真实浏览器在同一 commit、同一截点完成三策略首次导航：趋势 HOLD、震荡 FLAT、主升浪 HOLD，周线图、副图和参考交易统计均加载；主升浪截图 `output/playwright/sf-weekly-v20-main-rise-20260924.png`。顶部独立报价不可用和当前主力不可判定不等于周线策略失败。隔离预览按合同拒绝 `/reference-trading/streams` 的 403；进程已关闭。
- Release 和 Runtime promotion 尚未执行。
