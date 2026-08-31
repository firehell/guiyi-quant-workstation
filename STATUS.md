# 当前状态

更新时间：2026-08-31

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.6@8c14946357ba17236eab1dad1f6cace82ade37b5` 已发布：annotated tag 的 peeled commit、GitHub Release 与 release PR #273 merge commit 均精确指向该 commit；`main` 包含该 release commit。 |
| Runtime | 2026-08-31 21:15 CST 只读 health：本机仍绑定 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.5@e2376dc7f`，API、Web、Live 与 Alert 均从该 root 运行，API 版本 `1.9.5`，DB/Redis 正常。Live 为 operational `60`、subscribed `45`、`TRADING:45 / CLOSED:15`；盘后服务本轮已完成。整体仍为 `degraded`，原因是 Alert Strategy `15 ready / 45 unavailable`，不是 Runtime 版本漂移。未回填 Event、未发送通知。 |
| Database | production Alembic 为 `20260826_0042 (head)`。当前 Rule 为 `htdy_original_15m` 与 `subing_strategy_v1`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | 只读 `/api/alerts/products/jm` 确认 HTDY 为 `jm × 15m`，SuBing 为 product scope；Runtime health 确认两条 enabled Rule、scope product count `60`、audience count `2`。两种 authority 不合并。 |
| v1.9.5 Runtime | 在 v1.9.4 的 typed continuation seam 上修复收盘后 final catch-up：只有该路径可使用 existing operational、same-day、internally single-contract 的 `post_close` completed 1m/5m/15m snapshot；冻结 decision 贯穿逐 Bar 处理。普通 Live 不获得该 authority；snapshot 不一致仍 fail-closed，不同 frozen contract 仍只进入 `LIVE_CONTRACT_AUTHORITY_PENDING`。无 migration、Scope、transport 或策略公式变化。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-31 只读 Runtime health 显示自然 after-market 本轮已以 `passed` 完成：开始 `18:05:07 +08:00`、结束 `20:10:21 +08:00`、`attempts=1 / error_code=null`、覆盖 operational 60；未手工启动、补跑或回填。
- 同一 readback 显示 Alert processing 当前为 `ok`，但最近已持久 Event 与 transport attempt 仍是 `2026-08-27`；provider accepted 不等于微信送达，也不替代下一次自然 first-seen evidence。

## Pending Gate

- v1.9.6 已发布但尚未 Runtime promotion；须在独立 Runtime Gate 下准备 clean、detached 的 exact-tag root，验证最小连续状态后切换五项 launchd 服务并回读。当前 v1.9.5 Runtime 是唯一回滚根，必须保留。
- HTDY 的真实 PushPlus/微信送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- SuBing `v1.9.5` 自然 Live continuation seam evidence pending；当前 Alert Strategy 为 `15 ready / 45 unavailable`，不替代下一交易时段的 Live `60/60`、Alert `60 ready` 与跨交易日 cutoff 自然推进。不得以重启、回滚、回填或手工通知掩盖。
- 一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新仍须单独发生；2026-08-29 operator 已把效果快照 `through` 推到 `2026-08-28`，但不替代自然盘后 schema v3 status 写入。
- HTDY `jm × 15m` 下一次自然 15m completed Live bar 与 one-shot transport evidence 仍 pending（下次交易时段），不以 canary、replay 或手工发送替代。
