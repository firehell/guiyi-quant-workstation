# 当前状态

更新时间：2026-09-01

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.7@66c3be8035774a510e914e80a11e4669b15d42ab` 是当前最新 GitHub Release；`main`、annotated tag 与该 GitHub Release 精确一致并共同指向该 40 字符 commit，API 与 Web release identity 均为 `1.9.7`。历史 Git tag 保留作可复算引用。 |
| Runtime | 2026-08-31 晚间曾将五项 launchd 服务切换到 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.7-r2@b3efda13`；公开 health 读回 `live_unavailable / last_bar_at=null`，未取得首根 completed Live bar，已按 fail-closed 规则回滚一次。当前五项服务重新绑定 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.7-r3@66c3be80`；`/api/health` 返回 `200` 且版本为 `1.9.7`，`/api/runtime/health` 为 `degraded`，其中 `live_market=ok`、`alert=degraded`，当前仍非 `RUNTIME_READY`，未回填 Event、未发送通知。 |
| Database | production Alembic 为 `20260826_0042 (head)`。当前 Rule 为 `htdy_original_15m` 与 `subing_strategy_v1`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY Scope 为 `jm × 15m`；SuBing `scope_products` 为 operational 60。两种 authority 不合并。两条 Rule 均 enabled，Alert Runtime marker 已 enabled，audience count 2；未发生 Scope、Rule 或 audience 变更。 |
| v1.9.7 | 同一 physical contract 的跨交易日 completed 1m/5m/15m continuation 保持 typed identity seam；盘后只有 Canonical、Live reconciliation、策略效果增量刷新与 Daily Watch 都完成时才标记 `passed`。派生失败不撤销已成功 Canonical、不重试已完成 Canonical 写入；无 migration、Scope、transport 或策略公式变化。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-31 只读 Runtime health 显示自然 after-market 本轮已以 `passed` 完成：开始 `18:05:07 +08:00`、结束 `20:10:21 +08:00`、`attempts=1 / error_code=null`、覆盖 operational 60；未手工启动、补跑或回填。
- 同一 readback 显示 Alert processing 当前为 `ok`，但最近已持久 Event 与 transport attempt 仍是 `2026-08-27`；provider accepted 不等于微信送达，也不替代下一次自然 first-seen evidence。

## Pending Gate

- v1.9.7 Runtime 已绑定 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.7-r3@66c3be80`；该 root 仍非 `RUNTIME_READY`，因为 `/api/runtime/health` 为 `degraded`，`live_market=ok`、`alert=degraded`、`strategy_ready_product_count=0`、`strategy_unavailable_product_count=60`。历史 r2 `fail-closed` 回滚保留；任何未来 Runtime switch 仍需新的明确授权。
- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- v1.9.7 Runtime promotion 已因 fresh Live `last_bar_at=null` fail-closed 回滚；本轮不再尝试切换。当前 r3 只是已绑定的 degraded root，不是 ready promotion。下一次 promotion 须由新的明确授权开始，并先取得切换后的 completed Live bar、ready heartbeat 与连续状态读回。
- SuBing v1.9.7 自然 Live continuation seam 与严格盘后完成制 evidence pending；不以测试、startup replay、手工触发或回填替代。
- 一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新仍须单独发生；2026-08-29 operator 已把效果快照 `through` 推到 `2026-08-28`，但不替代自然盘后 schema v3 status 写入。
- HTDY `jm × 15m` 下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending（下次交易时段），不以 canary、replay 或手工发送替代。
