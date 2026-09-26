# SH 周线逐品种验收（2026-09-24）

- 固定截点 `2026-09-18T07:00:00.000001Z`。写前 SH Catalog revision `2b830666845de55df9cab8e9bf8dcefa22d869ae757f2aad77fea8560e301ccc`；11 个物理合约、5 个目标合约，162 根完整 D1 对应缺周、4 根有 D1 成功回执的成交额冲突、5 根合法质量中断。
- 精确包 SHA-256 `f42b76b1733f6db0e0d1842ec457890a3b12718cb9deefbcaea1b95c248ec751`：43 个 W1 月分区（38 新、5 旧）、166 根目标周。RQData 请求和 D1 写入均为 0。dry-run、43/43 旧指针、只读候选 MDS 叠加回读及独立 Review 通过；正式提交一次且 43/43 新指针与质量回读通过。写后 Catalog revision `a80720361679e3b8ba27be34ca242e72aafc2c64fbd80198a25dbeb02d5d7a3d`；刷新盘点只剩 5 根合法质量中断。
- Candidate readiness：趋势、震荡、主升浪主视图、图表、参考交易均 READY；主力控盘、涨跌动能、照妖镜 READY，MACD WARMING；震荡比较器 UNAVAILABLE，其他比较器 NOT_APPLICABLE。未造价或降低阈值。
- 正式候选 Scope v21：`develop@a3009d6e1e70be1f5d674d84c5e2ae66bb9a0046`，59/60，剩余 SM。后端相关 192 passed，Web 全部 683 passed、1 skipped，Web build、ruff、目标 OpenSpec strict、diff check 和独立 Review 通过。全量 OpenSpec 仍受未改 `reference-trading/spec.md` 的两处结构错误影响。正式只读 API smoke：三策略各图表、参考交易、MACD、比较器共 12 个 HTTP 200 且状态符合预期，SM 周线仍 409。
- 隔离真实浏览器在同一 commit、同一截点完成三策略首次导航：趋势 CLEAR、震荡 HOLD、主升浪 FLAT，周线图、辅助状态和参考交易统计均加载；主升浪截图 `output/playwright/sh-weekly-v21-main-rise-20260924.png`。顶部独立报价不可用和当前主力不可判定不等于周线策略失败。隔离预览按合同拒绝 `/reference-trading/streams` 的 403；进程已关闭。
- Release 和 Runtime promotion 尚未执行。
