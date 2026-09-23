# OI2611 W1 授权批次执行与页面验收

- 授权计划 SHA-256：`6411f51f11601783aae36c798561f35b1dd08acd3587b27291ddd1bcd79e2437`。执行前重新 prepare 完全一致，10 个旧 W1 指针均为 `old`；仅执行一次 `apply`，结果 `committed`。独立进程回读 10 个指针均为 `candidate`。
- 精确效果：新增 2025-11-28 至 2026-08-14 的 OI2611 W1 37 行，覆盖 10 个目标月。逐行 OHLCV 与计划一致；2026-08 原有 2 行不变。provider 下载 0、D1 写入 0。2025-11-17、18、21 的 `NONPOSITIVE_CLOSE` 保留为 2025-11-21 周的数据中断，不生成价格。
- [生产 Catalog 固定截点 readiness](post-apply-readiness.json)：OI2611 预期 41 周、价格 40 周、数据中断 1 周，三策略 W1 主状态和参考均 `READY`。该结果是数据验收，不代表 Scope 或 Runtime 启用。
- [隔离候选 API 回读](post-apply-preview-api.json)：在 `e61b8daa3` 代码及相同截点下，三策略的 chart/reference 和历史快照均返回 HTTP 200，chart/reference 状态为 `ready`。
- 浏览器只读候选预览在 `842d15388e9526b4d81046d3d9a8b8539d942d2d`（包含参考交易序列化修复 `69e61c3a1`）、截止 `2026-09-18T07:00:00.000001+00:00`、候选 API `127.0.0.1:8010` 身份一致时验收：趋势、震荡、主升浪三页 `data-chart-state=ready`，参考交易完成加载，无“数据身份冲突”。趋势已完成 9 笔、震荡 1 笔、主升浪 0 笔；均为页面参考统计，非成交。
- 页面验收时发现非持久化参考交易 API 输出 `storage_mode: null`，前端严格合同拒绝。修复为空值省略字段；定向 API 测试 38 项通过。该修复已集成并推送 `develop`。

尚未改变正式 Scope、main/tag/release 或 Runtime。后续若需发布或启用，须另过对应 Gate；本批次授权不覆盖这些操作。
