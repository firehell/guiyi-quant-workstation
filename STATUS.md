# 当前状态

更新时间：2026-09-01

本文件只记录当前 release、production Runtime、Scope、自然 evidence 与尚未完成的 Gate。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## Release、Runtime 与 Scope

| 项目 | 当前事实 |
|---|---|
| Release | `v1.9.9@c211b01e325726202f733fea2aa33ae2cf76b232` 是当前最新 GitHub Release；`main`、annotated tag 的 peeled commit 与该 GitHub Release 精确一致，API 与 Web release identity 均为 `1.9.9`。该最小热修从 `main/v1.9.8@7c074ab41` 只纳入 `fbf468cba` 的 Alert startup queue reconciliation 修复及必要 release 元数据；未夹带其余 `main..develop` Web/文档提交。 |
| Runtime | 2026-09-01 将五项 launchd 服务一次切换到 clean、detached 的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.9-r1@c211b01e`；API/Web 为 `1.9.9`，五项 exact root/commit 一致。Alert 于 `12:06:44 +08:00` 完成 restore/reconciliation，达到 `60/60 ready / 0 unavailable / strategy_state=ready`，startup 未新增 Event 或 transport attempt。首根自然 Live Gate 于午休后失败：Live 已 `60/60 subscribed` 且持续收到 completed Bar，但 completed 1m PubSub 在 fresh heartbeat 写入前可见，Alert continuation 读取旧 `live_available=false`，使 41 个已收到首 Bar 的 SuBing 产品（含 JM）降为 `STALE_OR_IDENTITY_INVALID`，仅 19 个未命中该窗口的产品保持 ready；整体 Runtime 为 degraded。未重启、回滚、补评、回填或手工通知。`v1.9.7-r3@66c3be80` 保留为 clean、detached rollback root。 |
| Database | production Alembic 为 `20260826_0042 (head)`。当前 Rule 为 `htdy_original_15m` 与 `subing_strategy_v1`。 |
| Market Runtime Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | HTDY Scope 为 `jm × 15m`；SuBing `scope_products` 为 operational 60。两种 authority 不合并。两条 Rule 均 enabled，Alert Runtime marker 已 enabled，audience count 2；未发生 Scope、Rule 或 audience 变更。 |
| v1.9.8 | Alert startup/final catch-up 的 Live snapshot 冻结在 causal `through` 上界，避免批量 restore 期间新到达 Bar 污染较早产品；Runtime status 写 schema v4，保留每个 unavailable 产品的固定公开 reason，并兼容读取 v1/v2/v3。无 migration、Scope、Rule、audience、transport 或策略公式变化。 |
| v1.9.9 | frozen final-catch-up watermark 队列 reconciliation：严格更旧 Bar 丢弃，相同 watermark 仍校验，更新 Bar 只推进且不补发；reconciliation 结束前保持 warming，只有 active60 全 ready 才写 `strategy_ready_at`。完整后端、Web、Ruff、Mypy、canonical、OpenSpec 与 secret scan 已通过，Standards/Spec 复审均 no findings；当前已 `RELEASED`，已完成 exact-tag Runtime 切换，但自然首 Bar Gate failed，不能标记 `RUNTIME_READY`。 |

Alert transport 为 PushPlus；provider accepted 不等于微信送达。

## 自然 evidence

- 2026-08-31 只读 Runtime health 显示自然 after-market 本轮已以 `passed` 完成：开始 `18:05:07 +08:00`、结束 `20:10:21 +08:00`、`attempts=1 / error_code=null`、覆盖 operational 60；未手工启动、补跑或回填。
- 2026-09-01 `13:46:05 +08:00`，JM 的 HTDY 15m 自然 first-seen buy Event 已持久化并触发一次 PushPlus transport；provider accepted 仅表示服务端受理，不等于微信送达。SuBing 当前交易日没有 Strategy Action Event。

## Pending Gate

- v1.9.9 已 `RELEASED` 并完成一次 exact-tag Runtime 切换，但首根自然 completed Live Gate 已失败：Alert 为 `19/60 ready`、`41/60 unavailable`，不得标记 `RUNTIME_READY`。必须以修复后的新 release 重新完成该 Gate。
- HTDY 的 2026-09-01 JM 15m natural Event 已取得 provider acceptance；微信实际送达，以及 D1/W1 `canonical_updated` 的自然 Event identity/evidence，仍须分别核验；不以测试、synthetic event、replay 或手工发送补证。
- v1.9.7-r3 当前仅作为 clean、detached rollback root 保留，已不再承载五项正式服务。
- 修复后的 SuBing 自然 Live continuation seam 与严格盘后完成制 evidence 必须重新取得；不以测试、startup replay、手工触发或回填替代。
- 一次 owner PushPlus canary 仍是独立 Gate。
- SuBing Candidate 的 prospective OOS 按其 protocol 独立累积，retrospective 不回填 OOS。
- 第一次自然盘后 derived 增量刷新仍须单独发生；2026-08-29 operator 已把效果快照 `through` 推到 `2026-08-28`，但不替代自然盘后 schema v3 status 写入。
