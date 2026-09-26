# 牛哇周线 60 品种候选验收（2026-09-24）

- 精确代码：`develop` / 本地 `codex/release-newow-weekly-60-rc` 均指向 `10e6805665ede2cff18c3ebd40808dad11471529`；`origin/develop` 同提交。
- 相对现役 `v1.10.30@120c5c9490b9909bb64b2e55a5fb5893e57a04c0`，本候选新增 PF、PK、PL、PR、PX、RS、SF、SH、SM、SR；正式能力接口只读回读为 `newow_product_capabilities_v22`，W1 60/60，见 `formal-capability-readback.json`。候选预览接口保留独立的 v9 wire contract。
- 固定截点：`2026-09-18T07:00:00.000001Z`；60 个 operational 品种 × 趋势、震荡、主升浪 = 180 项。
- 真实 Catalog/MDS 只读策略审计：v1 组 41 品种、123 项，v2 组 19 品种、57 项，合计 180/180 已判定。主图及参考交易 179 READY、1 WARMING；唯一非 READY 为 RS 震荡，主图 `NEWOW_OSCILLATION_WARMING`，参考 `NEWOW_SOURCE_PRICE_UNAVAILABLE_REWARMING`。两组均 `audited / complete`、无预算耗尽、provider 请求 0、写入 0。详见 `strategy-180-summary.json` 和两份原始 `readiness-*.json`。
- 同一代码与截点的隔离只读浏览器首次导航：180 个不同品种×策略组合均有终态、参考摘要可见；页面主图 179 READY、RS 震荡 1 WARMING，与审计逐项一致。原始 `browser-matrix.jsonl` 含 192 次尝试：初始过高并发引发 8 次 `429 NEWOW_RESOURCE_BUSY`，另 4 次为主动中断浏览器时关闭上下文；改为每个 Preview API 同时一个页面后，所有 180 项均在新的首次导航通过。候选预览按合同拒绝 `/reference-trading/streams` 的 403，不属于牛哇策略接口失败。详见 `page-180-summary.json`。
- 定向后端测试 143 passed；前端相关测试 76 passed；Web production build 成功；`git diff --check origin/main..HEAD` 通过。原始输出见同目录 `pytest.txt`、`web-tests.txt`、`web-build.txt`。

本包仅为精确代码候选及验收证据；未确定发布版本号，未执行 main merge、tag、GitHub Release 或 Runtime promotion。现役正式周线仍为 50/60。后续须冻结发布版本及纳入范围，按发布 Gate 审核，再分别取得 Release 与 Runtime 授权；新 Runtime 自然业务和 weekly audit 仍需单独验收。
