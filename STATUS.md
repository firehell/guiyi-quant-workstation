# 当前状态

更新时间：2026-09-01

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.8@7c074ab41e05b6056e08323cf111655765a9bfa5` 是当前最新 GitHub Release；`main`、annotated tag 的 peeled commit 与该 GitHub Release 精确一致，API 与 Web release identity 均为 `1.9.8`。该最小热修从旧 `main@66c3be80` 只纳入 `dd0eb643b` 的 Alert startup causal snapshot/schema-v4 readiness 修复及必要 release 元数据；未夹带其余 `main..develop` Web/文档提交。 |
| Runtime | 2026-09-01 将五项 launchd 服务一次切换到 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.8-r1@7c074ab41`；Live 在首个完整 1m 边界后达到 `60 subscribed / live_market=ok / last_bar_at=2026-09-01T02:32:00Z`，Alert restore 于 `2026-09-01T02:44:58Z` 完成并写出 schema-v4 reason，但结果为 `0 ready / 60 unavailable`，60 个 reason 均为 `STALE_INPUT`，未达到 `RUNTIME_READY`。已按 fail-closed 规则只回滚一次；当前五项服务重新绑定 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.7-r3@66c3be80`，回滚后 Live 已恢复到 `last_bar_at=2026-09-01T02:47:00Z`。startup/promotion 未新增 Event、未调用 transport、未发送 canary。 |
| Database | production Alembic 为 `20260826_0042 (head)`。当前 Rule 为 `htdy_original_15m` 与 `subing_strategy_v1`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY Scope 为 `jm × 15m`；SuBing `scope_products` 为 operational 60。两种 authority 不合并。两条 Rule 均 enabled，Alert Runtime marker 已 enabled，audience count 2；未发生 Scope、Rule 或 audience 变更。 |
| v1.9.8 | Alert startup/final catch-up 的 Live snapshot 冻结在 causal `through` 上界，避免批量 restore 期间新到达 Bar 污染较早产品；Runtime status 写 schema v4，保留每个 unavailable 产品的固定公开 reason，并兼容读取 v1/v2/v3。无 migration、Scope、Rule、audience、transport 或策略公式变化。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-31 只读 Runtime health 显示自然 after-market 本轮已以 `passed` 完成：开始 `18:05:07 +08:00`、结束 `20:10:21 +08:00`、`attempts=1 / error_code=null`、覆盖 operational 60；未手工启动、补跑或回填。
- 同一 readback 显示 Alert processing 当前为 `ok`，但最近已持久 Event 与 transport attempt 仍是 `2026-08-27`；provider accepted 不等于微信送达，也不替代下一次自然 first-seen evidence。

## Pending Gate

- v1.9.8 已 `RELEASED`，但 Runtime promotion 因 active60 全部 `STALE_INPUT` fail-closed 回滚，当前不是 `RUNTIME_READY`。本轮不再尝试切换；后续须先只读定位共同 freshness authority，再经过新的代码/测试/Release Gate 与新的 Runtime 授权。
- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- 当前 v1.9.7-r3 仅是已恢复的回滚根，不是 ready promotion；回滚后 Alert 正在重新 restore，已知该旧版本此前为 `0 ready / 60 unavailable` 且未保存 reason map。
- SuBing v1.9.8 自然 Live continuation seam 与严格盘后完成制 evidence pending；不以测试、startup replay、手工触发或回填替代。
- 一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新仍须单独发生；2026-08-29 operator 已把效果快照 `through` 推到 `2026-08-28`，但不替代自然盘后 schema v3 status 写入。
- HTDY `jm × 15m` 下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending（下次交易时段），不以 canary、replay 或手工发送替代。
